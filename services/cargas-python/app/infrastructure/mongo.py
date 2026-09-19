"""Persistencia asíncrona. Toda escritura de procesamiento comprueba el lease en la transacción."""
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from uuid import uuid4

from bson import Decimal128
from gridfs import AsyncGridFSBucket
from pymongo import AsyncMongoClient, ReturnDocument, ReadPreference
from pymongo.errors import DuplicateKeyError
from pymongo.read_concern import ReadConcern
from pymongo.write_concern import WriteConcern

from app.domain.excel import fingerprint, money


def now():
    return datetime.now(timezone.utc)


def audit(actor):
    return dict(UsuarioCreacion=actor, FechaCreacion=now(), UsuarioModificacion=None, FechaModificacion=None)


def modification():
    return dict(UsuarioModificacion='cargas-python', FechaModificacion=now())


class LeaseLost(Exception):
    pass


class Repository:
    def __init__(self, settings):
        self.settings = settings
        self.client = AsyncMongoClient(settings.mongo_uri, serverSelectionTimeoutMS=3000,
                                       connectTimeoutMS=3000, socketTimeoutMS=10000, tz_aware=True)
        self.db = self.client.get_database(settings.database, read_concern=ReadConcern('majority'),
                                          write_concern=WriteConcern('majority'), read_preference=ReadPreference.PRIMARY)
        self.files = AsyncGridFSBucket(self.db)

    async def close(self):
        await self.client.close()

    async def transaction(self, callback):
        async with self.client.start_session() as session:
            return await session.with_transaction(callback, read_concern=ReadConcern('snapshot'),
                                                  write_concern=WriteConcern('majority'),
                                                  read_preference=ReadPreference.PRIMARY)

    async def indexes(self):
        await self.db.CargaDetalle.create_index([('IdCarga', 1), ('IndiceOriginal', 1)], unique=True)
        await self.db.CargaTarea.create_index('IdCarga', unique=True)
        await self.db.CargaTarea.create_index([('EstadoTarea', 1), ('ProximoIntento', 1), ('LeaseHasta', 1)])
        await self.db.Pedido.create_index('IdSolicitud', unique=True)
        await self.db.PedidoDetalle.create_index([('IdPedido', 1), ('IdProducto', 1)], unique=True)
        await self.db['fs.files'].create_index([('metadata.cargaId', 1), ('metadata.tipo', 1)])
        # GridFS creates its own standard indexes at first upload.

    async def ping(self):
        await self.db.command('ping')

    async def upload(self, file_id, carga_id, name, kind, content):
        await self.files.upload_from_stream_with_id(file_id, name, content,
            metadata=dict(cargaId=carga_id, tipo=kind, nombreOriginal=name, fecha=now()))

    async def download(self, file_id):
        stream = await self.files.open_download_stream(file_id)
        try:
            return await stream.read()
        finally:
            await stream.close()

    async def receive(self, name, content, actor, correlation):
        carga_id = 'CG-' + str(uuid4())
        file_id = 'ENT-' + carga_id
        await self.upload(file_id, carga_id, name, 'ENTRADA', content)
        carga = dict(_id=carga_id, NombreArchivo=name, FechaCarga=now(), TotalFilas=0,
                     CantAceptadas=0, CantRechazadas=0, CantDuplicadas=0, IdEstadoProceso='PROCESANDO',
                     ArchivoEntradaId=file_id, ArchivoReporteId=None, CorrelationId=correlation, Log=None, **audit(actor))
        tarea = dict(_id='CT-' + str(uuid4()), IdCarga=carga_id, EstadoTarea='PENDIENTE', Intentos=0,
                     LeaseOwner=None, LeaseHasta=None, ProximoIntento=now(), FechaInicio=None,
                     FechaFin=None, UltimoError=None, Secuencia=0, **audit(actor))

        async def save(session):
            await self.db.Carga.insert_one(carga, session=session)
            await self.db.CargaTarea.insert_one(tarea, session=session)
        # An ambiguous commit is left recoverable; never delete an input that may be referenced.
        await self.transaction(save)
        return carga_id

    def owned(self, task):
        return dict(_id=task['_id'], EstadoTarea='EN_PROCESO', LeaseOwner=task['LeaseOwner'],
                    Intentos=task['Intentos'], LeaseHasta={'$gt': now()})

    async def fence(self, task, session):
        result = await self.db.CargaTarea.update_one(self.owned(task),
                         {'$inc': {'Secuencia': 1}, '$set': modification()}, session=session)
        if result.matched_count != 1:
            raise LeaseLost()

    async def claim(self, owner):
        stamp = now()
        return await self.db.CargaTarea.find_one_and_update(
            {'Intentos': {'$lt': self.settings.max_attempts}, '$or': [
                {'EstadoTarea': 'PENDIENTE', 'ProximoIntento': {'$lte': stamp}},
                {'EstadoTarea': 'EN_PROCESO', 'LeaseHasta': {'$lte': stamp}}]},
            {'$set': dict(EstadoTarea='EN_PROCESO', LeaseOwner=owner,
                          LeaseHasta=stamp + timedelta(seconds=self.settings.lease_seconds),
                          FechaInicio=stamp, FechaFin=None, **modification()), '$inc': {'Intentos': 1}},
            sort=[('ProximoIntento', 1)], return_document=ReturnDocument.AFTER)

    async def heartbeat(self, task):
        result = await self.db.CargaTarea.update_one(self.owned(task), {'$set': dict(
            LeaseHasta=now() + timedelta(seconds=self.settings.lease_seconds), **modification())})
        if result.matched_count != 1:
            raise LeaseLost()

    async def reap_exhausted(self):
        # A crash during the last attempt must not leave EN_PROCESO forever.
        query = {'EstadoTarea': 'EN_PROCESO', 'LeaseHasta': {'$lte': now()},
                 'Intentos': {'$gte': self.settings.max_attempts}}
        async for task in self.db.CargaTarea.find(query):
            async def finish(session):
                result = await self.db.CargaTarea.update_one({'_id': task['_id'], **query}, {'$set': dict(
                    EstadoTarea='FALLIDA', FechaFin=now(), UltimoError='LEASE_AGOTADO',
                    LeaseOwner=None, LeaseHasta=None, **modification())}, session=session)
                if result.matched_count:
                    await self.db.Carga.update_one({'_id': task['IdCarga'], 'IdEstadoProceso': {'$ne': 'PROCESADA'}},
                        {'$set': dict(IdEstadoProceso='ERROR', Log='LEASE_AGOTADO', **modification())}, session=session)
            await self.transaction(finish)

    async def fail(self, task, reason):
        final = task['Intentos'] >= self.settings.max_attempts
        async def save(session):
            await self.fence(task, session)
            await self.db.CargaTarea.update_one({'_id': task['_id']}, {'$set': dict(
                EstadoTarea='FALLIDA' if final else 'PENDIENTE', LeaseOwner=None, LeaseHasta=None,
                ProximoIntento=now() + timedelta(milliseconds=self.settings.retry_base_ms * task['Intentos']),
                FechaFin=now() if final else None, UltimoError=reason, **modification())}, session=session)
            if final:
                await self.db.Carga.update_one({'_id': task['IdCarga'], 'IdEstadoProceso': {'$ne': 'PROCESADA'}},
                    {'$set': dict(IdEstadoProceso='ERROR', Log=reason, **modification())}, session=session)
        await self.transaction(save)

    async def set_total(self, task, total):
        async def save(session):
            await self.fence(task, session)
            await self.db.Carga.update_one({'_id': task['IdCarga']},
                 {'$set': dict(TotalFilas=total, **modification())}, session=session)
        await self.transaction(save)

    async def active(self, document, session, legacy=True):
        if document is None:
            return False
        if 'IdEstado' not in document:
            return legacy  # Existing Java products/users/warehouses have no state field.
        if document['IdEstado'] == 'ACTIVO':
            return True
        return await self.db.Estado.find_one({'_id': document['IdEstado'], 'Nombre': 'ACTIVO'}, session=session) is not None

    async def business(self, row, session):
        v = row.values
        warehouse = await self.db.Almacen.find_one({'_id': v['ALMACENID']}, session=session)
        if not await self.active(warehouse, session):
            return 'ALMACEN_NO_EXISTE_O_INACTIVO'
        product = await self.db.Producto.find_one({'SKU': v['SKU']}, session=session)
        if not await self.active(product, session):
            return 'SKU_NO_EXISTE_O_INACTIVO'
        relation = await self.db.UsuarioAlmacen.find_one({'IdUsuario': product.get('IdUsuario'),
                                                       'IdAlmacen': v['ALMACENID']}, session=session)
        if relation is None:
            return 'SKU_NO_PERTENECE_AL_ALMACEN'
        client = await self.db.Cliente.find_one({'_id': v['CLIENTEID']}, session=session)
        if client is None:
            return 'CLIENTE_NO_EXISTE'
        user = await self.db.Usuario.find_one({'_id': client.get('IdUsuario')}, session=session)
        if not await self.active(user, session):
            return 'CLIENTE_USUARIO_INACTIVO'
        role = await self.db.Rol.find_one({'_id': user.get('IdRol'), 'Nombre': 'COMPRADOR'}, session=session)
        if role is None:
            return 'CLIENTE_NO_ES_COMPRADOR'
        zones = await self.db.Zona.find({'$or': [{'_id': v['ZONAENTREGA']}, {'Codigo': v['ZONAENTREGA']}]}, session=session).to_list()
        active_zones = [z for z in zones if await self.active(z, session, legacy=False)]
        if len(active_zones) != 1:
            return 'ZONA_NO_EXISTE_O_INACTIVA'
        row.resolved = dict(product=product, client=client, user=user, zone=active_zones[0])
        return None

    async def process_block(self, task, carga, rows):
        # These rows belong to a freshly parsed workbook; retries reset only business results.
        syntax = [list(r.errors) for r in rows]
        async def save(session):
            await self.fence(task, session)
            indices = [r.index for r in rows]
            count = await self.db.CargaDetalle.count_documents({'IdCarga': carga['_id'], 'IndiceOriginal': {'$in': indices}}, session=session)
            if count == len(rows):
                return 'YA_PERSISTIDO'
            if count:
                raise RuntimeError('BLOQUE_PARCIAL_INCONSISTENTE')
            for row, errors in zip(rows, syntax):
                row.errors = list(errors)
                row.resolved = {}
                if not row.errors:
                    error = await self.business(row, session)
                    if error:
                        row.errors.append(error)
            invalid = any(r.errors for r in rows)
            state, reason, pedido_id = 'RECHAZADA', 'SOLICITUD_INVALIDA', None
            if not invalid:
                digest = fingerprint(rows[0].resolved['user']['_id'], rows)
                previous = await self.db.Pedido.find_one({'IdSolicitud': rows[0].values['SOLICITUDID']}, session=session)
                if previous:
                    if previous.get('HuellaContenido') == digest:
                        state, reason, pedido_id = 'DUPLICADA', 'SOLICITUD_DUPLICADA', previous['_id']
                    else:
                        reason = 'SOLICITUD_ID_CON_CONTENIDO_DISTINTO'
                else:
                    pedido_id = await self.create_order(carga, rows, digest, session)
                    state, reason = 'ACEPTADA', 'OK'
            for row in rows:
                v = row.values
                doc = dict(_id='CD-' + str(uuid4()), IdCarga=carga['_id'], IndiceOriginal=row.index,
                           IdSolicitud=v['SOLICITUDID'], FechaSolicitud=row.date, IdCliente=v['CLIENTEID'],
                           IdAlmacen=v['ALMACENID'], IdZona=row.resolved.get('zone', {}).get('_id'), SKU=v['SKU'],
                           IdProducto=row.resolved.get('product', {}).get('SKU'), Cantidad=v['CANTIDAD'],
                           IdPedido=pedido_id, IdEstado=state, Log=';'.join(row.errors) if row.errors else reason,
                           Original={k: x.isoformat() if isinstance(x, datetime) else x for k, x in v.items()},
                           **audit(carga['UsuarioCreacion']))
                await self.db.CargaDetalle.update_one({'IdCarga': carga['_id'], 'IndiceOriginal': row.index},
                                                      {'$setOnInsert': doc}, upsert=True, session=session)
            return state
        try:
            return await self.transaction(save)
        except DuplicateKeyError:
            # A Java/other carga winner is now read in a fresh transaction.
            return await self.transaction(save)

    async def create_order(self, carga, rows, digest, session):
        pedido_id = 'PED-' + str(uuid4())
        subtotal, weight = Decimal(0), Decimal(0)
        details = []
        for row in sorted(rows, key=lambda r: r.values['SKU']):
            product, quantity = row.resolved['product'], row.values['CANTIDAD']
            price, unit_weight = money(product['Precio'].to_decimal()), product['Peso'].to_decimal()
            partial = money(price * quantity)
            subtotal += partial
            weight += unit_weight * quantity
            details.append(dict(_id='DET-' + str(uuid4()), IdPedido=pedido_id, IdProducto=product['SKU'],
                                IdUsuarioVendedor=product['IdUsuario'], Cantidad=quantity,
                                PrecioUnitario=Decimal128(price), PesoUnitario=Decimal128(unit_weight),
                                Subtotal=Decimal128(partial), **audit(carga['UsuarioCreacion'])))
        first = rows[0]
        await self.db.Pedido.insert_one(dict(_id=pedido_id, IdSolicitud=first.values['SOLICITUDID'],
            IdCliente=first.resolved['client']['_id'], IdUsuarioComprador=first.resolved['user']['_id'],
            IdAlmacen=first.values['ALMACENID'], ZonaEntrega=first.values['ZONAENTREGA'], HuellaContenido=digest,
            IdEstado='RECIBIDO', Subtotal=Decimal128(money(subtotal)), Envio=None, Total=None,
            PesoTotal=Decimal128(weight), CorrelationId=carga['CorrelationId'], AnulacionSolicitada=False,
            FechaSolicitudAnulacion=None, EstadoReserva='NINGUNA', **audit(carga['UsuarioCreacion'])), session=session)
        await self.db.PedidoDetalle.insert_many(details, session=session)
        return pedido_id

    async def counts(self, carga_id, session=None):
        cursor = await self.db.CargaDetalle.aggregate([
            {'$match': {'IdCarga': carga_id}}, {'$group': {'_id': '$IdEstado', 'n': {'$sum': 1}}}], session=session)
        values = {d['_id']: d['n'] async for d in cursor}
        return dict(CantAceptadas=values.get('ACEPTADA', 0), CantRechazadas=values.get('RECHAZADA', 0),
                    CantDuplicadas=values.get('DUPLICADA', 0))

    async def finish(self, task, report_id):
        async def save(session):
            await self.fence(task, session)
            carga = await self.db.Carga.find_one({'_id': task['IdCarga']}, session=session)
            counts = await self.counts(carga['_id'], session)
            if sum(counts.values()) != carga['TotalFilas']:
                raise RuntimeError('CONTADORES_INCONSISTENTES')
            await self.db.Carga.update_one({'_id': carga['_id']}, {'$set': dict(
                **counts, IdEstadoProceso='PROCESADA', ArchivoReporteId=report_id, Log=None, **modification())}, session=session)
            await self.db.CargaTarea.update_one({'_id': task['_id']}, {'$set': dict(EstadoTarea='COMPLETADA',
                LeaseHasta=None, LeaseOwner=None, FechaFin=now(), UltimoError=None, **modification())}, session=session)
        await self.transaction(save)
