import asyncio
import time
from contextlib import suppress
from uuid import uuid4

from app.domain.excel import parse, blocks, validate_block, report, WorkbookError
from app.infrastructure.mongo import LeaseLost
from app.logging import event


class Worker:
    def __init__(self, repository):
        self.repo = repository
        self.settings = repository.settings
        self.owner = 'cargas-' + str(uuid4())

    async def heartbeat(self, task):
        while True:
            await asyncio.sleep(self.settings.lease_seconds / 3)
            await self.repo.heartbeat(task)

    async def process(self, task):
        carga = await self.repo.db.Carga.find_one({'_id': task['IdCarga']})
        if carga['IdEstadoProceso'] == 'PROCESADA':
            # Redelivery after successful completion keeps the same current report.
            await self.repo.download(carga['ArchivoReporteId'])
            await self.repo.finish(task, carga['ArchivoReporteId'])
            return
        content = await self.repo.download(carga['ArchivoEntradaId'])
        rows = await asyncio.to_thread(parse, content, self.settings.max_upload_bytes)
        await self.repo.set_total(task, len(rows))
        for block in blocks(rows):
            validate_block(block)
            result = await self.repo.process_block(task, carga, block)
            event('bloque', cargaId=carga['_id'], tareaId=task['_id'], intento=task['Intentos'],
                  correlationId=carga['CorrelationId'], indice=block[0].index, resultado=result)
        details = await self.repo.db.CargaDetalle.find({'IdCarga': carga['_id']}).sort('IndiceOriginal', 1).to_list()
        content = await asyncio.to_thread(report, details)
        report_id = f'REP-{carga["_id"]}-{task["Intentos"]}'
        await self.repo.upload(report_id, carga['_id'], f'reporte-{carga["_id"]}.xlsx', 'REPORTE', content)
        await self.repo.finish(task, report_id)
        # Only the referenced report is functional. Clean abandoned earlier attempts after publishing.
        async for old in self.repo.db['fs.files'].find({'metadata.cargaId': carga['_id'], 'metadata.tipo': 'REPORTE', '_id': {'$ne': report_id}}):
            try:
                await self.repo.files.delete(old['_id'])
            except Exception:
                event('limpieza_reporte', cargaId=carga['_id'], resultado='PENDIENTE')

    async def once(self):
        await self.repo.reap_exhausted()
        task = await self.repo.claim(self.owner)
        if task is None:
            return False
        start = time.monotonic()
        heartbeat = asyncio.create_task(self.heartbeat(task))
        processing = asyncio.create_task(self.process(task))
        try:
            done, _ = await asyncio.wait({heartbeat, processing}, return_when=asyncio.FIRST_COMPLETED)
            if heartbeat in done:
                await heartbeat  # Propagate lost lease / Mongo failure; stop the stale writer.
            await processing
            result = 'COMPLETADA'
        except asyncio.CancelledError:
            raise
        except LeaseLost:
            result = 'LEASE_PERDIDO'
        except Exception as exc:
            processing.cancel()
            with suppress(asyncio.CancelledError, Exception):
                await processing
            result = str(exc) if isinstance(exc, WorkbookError) else 'ERROR_TECNICO'
            try:
                await self.repo.fail(task, result)
            except LeaseLost:
                result = 'LEASE_PERDIDO'
        finally:
            for future in (heartbeat, processing):
                future.cancel()
                with suppress(asyncio.CancelledError, Exception):
                    await future
        event('tarea', cargaId=task['IdCarga'], tareaId=task['_id'], intento=task['Intentos'],
              resultado=result, duracionMs=round((time.monotonic() - start) * 1000))
        return True

    async def run(self):
        while True:
            try:
                await self.repo.indexes()
                while True:
                    if not await self.once():
                        await asyncio.sleep(self.settings.poll_ms / 1000)
            except asyncio.CancelledError:
                raise
            except Exception:
                event('worker', resultado='DEPENDENCIA_NO_DISPONIBLE')
                await asyncio.sleep(self.settings.poll_ms / 1000)
