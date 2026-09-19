import { createEnvironmentInjector, EnvironmentInjector, importProvidersFrom } from '@angular/core';
import { TestBed, fakeAsync, tick } from '@angular/core/testing';
import { HttpClient, HttpErrorResponse, provideHttpClient, withInterceptors } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { provideRouter, Router } from '@angular/router';
import { provideNoopAnimations } from '@angular/platform-browser/animations';
import { of } from 'rxjs';
import { ADMIN_ROUTES } from './admin.routes';
import { AdminPedidosApiService, AdminCargasApiService, countsOf, filterOrders, pollCarga } from './core/api';
import { ADMIN_CONFIG, RECENT_STORAGE } from './core/config';
import { RecentLoadsService, RECENT_KEY } from './core/recent-loads';
import { AdminFeedback, errorMessage, FileDownloader, progressOf, reportFilename, validateFile } from './core/presentation';
import { Carga, PedidoAdmin } from './core/models';
import { LoadsComponent } from './features/loads';
import { AdminLayout } from './admin-layout';
import { RouterTestingHarness } from '@angular/router/testing';

const envelope=<T>(data:T)=>({code:200,statusCode:'HTTP_200_OK',message:'OK',data});
const pedido=(id:string,estado:PedidoAdmin['estado']='RECIBIDO'):PedidoAdmin=>({pedidoId:id,estado,almacenId:'ALM-01',subtotal:10,envio:null,total:null,pesoTotal:1,anulacionSolicitada:false,items:[]});
const carga=(estado:Carga['estado']='PROCESANDO'):Carga=>({cargaId:'CG-test',estado,totales:{filas:0,aceptadas:0,rechazadas:0,duplicadas:0},reporte:estado==='PROCESADA'?'/cargas/CG-test/reporte':null});
class MemoryStorage implements Storage {
 private data=new Map<string,string>();get length(){return this.data.size;}clear(){this.data.clear();}getItem(k:string){return this.data.get(k)??null;}key(i:number){return [...this.data.keys()][i]??null;}removeItem(k:string){this.data.delete(k);}setItem(k:string,v:string){this.data.set(k,v);}
}
describe('ADMIN remoto: contratos y estado focalizados',()=>{
 let http:HttpTestingController;let storage:MemoryStorage;
 beforeEach(()=>{storage=new MemoryStorage();TestBed.configureTestingModule({providers:[provideHttpClient(withInterceptors([(r,next)=>next(r.clone({setHeaders:{'X-Host-Test':'inherited'}}))])),provideHttpClientTesting(),provideRouter([]),provideNoopAnimations(),{provide:RECENT_STORAGE,useValue:storage},{provide:ADMIN_CONFIG,useValue:{javaApi:'/api/java',despachosApi:'/api/despachos',cargasApi:'/api/cargas',maxUploadBytes:10485760,maxOrderPages:2}},{provide:AdminFeedback,useValue:{show:jasmine.createSpy('feedback')}}]});http=TestBed.inject(HttpTestingController);});
 afterEach(()=>http.verify());
 it('exporta rutas relativas y redirect vacío a dashboard',()=>{expect(ADMIN_ROUTES[0]).toEqual({path:'',pathMatch:'full',redirectTo:'dashboard'});expect(ADMIN_ROUTES[1].children?.map(r=>r.path)).toEqual(['dashboard','cargas','revision']);expect(ADMIN_ROUTES.some(r=>r.path==='admin')).toBeFalse();});
 it('providers exportados heredan HttpClient del host e interceptor, sin registrar auth',()=>{
  const parent=TestBed.inject(EnvironmentInjector);const child=createEnvironmentInjector(ADMIN_ROUTES[1].providers??[],parent);
  expect(child.get(HttpClient)).toBe(TestBed.inject(HttpClient));child.get(AdminPedidosApiService).detail('PED-one').subscribe();
  const req=http.expectOne('/api/java/pedidos/PED-one');expect(req.request.headers.get('X-Host-Test')).toBe('inherited');req.flush(envelope(pedido('PED-one')));child.destroy();
 });
 it('deriva conteos sin inventar estados o totales',()=>{const counts=countsOf([pedido('1'),pedido('2','REQUIERE_REVISION'),pedido('3','DESPACHADO'),pedido('4','COMPENSANDO')]);expect(counts.RECIBIDO).toBe(1);expect(counts.REQUIERE_REVISION).toBe(1);expect(counts.ANULADO).toBe(0);expect(Object.values(counts).reduce((a,b)=>a+b,0)).toBe(4);});
 it('paginación termina al recibir menos de 50 y conserva pedidos',()=>{let total=0;TestBed.inject(AdminPedidosApiService).all().subscribe(s=>{total=s.pedidos.length;expect(s.limited).toBeFalse();});http.expectOne('/api/java/pedidos?pagina=0').flush(envelope(Array.from({length:50},(_,i)=>pedido('PED-'+i))));http.expectOne('/api/java/pedidos?pagina=1').flush(envelope([pedido('PED-last')]));expect(total).toBe(51);http.expectNone('/api/java/pedidos?pagina=2');});
 it('límite seguro corta páginas completas y marca métricas parciales',()=>{let limited=false;TestBed.inject(AdminPedidosApiService).all().subscribe(s=>limited=s.limited);for(let n=0;n<2;n++)http.expectOne('/api/java/pedidos?pagina='+n).flush(envelope(Array.from({length:50},(_,i)=>pedido('PED-'+(n*50+i)))));expect(limited).toBeTrue();http.expectNone('/api/java/pedidos?pagina=2');});
 it('revisión y búsqueda filtran localmente por ID y estado',()=>{expect(filterOrders([pedido('PED-abc','REQUIERE_REVISION'),pedido('PED-xyz','REQUIERE_REVISION'),pedido('PED-abd')],'ab','REQUIERE_REVISION').map(p=>p.pedidoId)).toEqual(['PED-abc']);});
 it('detalle recupera pasos, guía y compensaciones reales',()=>{const detail={...pedido('PED-one'),guia:{id:'G-1',estado:'ACTIVO'},pasos:[{paso:'GENERAR_GUIA',estado:'FALLIDO',intentos:3,ms:23}],compensaciones:[]};TestBed.inject(AdminPedidosApiService).detail('PED-one').subscribe(p=>expect(p).toEqual(detail));http.expectOne('/api/java/pedidos/PED-one').flush(envelope(detail));});
 it('reintento .NET 202 envía body null y conserva aceptación asíncrona',()=>{let accepted=false;TestBed.inject(AdminPedidosApiService).retry('PED-one').subscribe(p=>accepted=p.reintentoSolicitado);const req=http.expectOne('/api/despachos/despachos/PED-one/reintento');expect(req.request.body).toBeNull();req.flush(envelope({pedidoId:'PED-one',reintentoSolicitado:true}),{status:202,statusText:'Accepted'});expect(accepted).toBeTrue();});
 it('reintento 409 produce conflicto seguro',()=>{let message='';TestBed.inject(AdminPedidosApiService).retry('PED-one').subscribe({error:e=>message=errorMessage(e)});http.expectOne('/api/despachos/despachos/PED-one/reintento').flush({}, {status:409,statusText:'Conflict'});expect(message).toContain('estado actual');});
 it('anulación Java acepta 202/200 sin body funcional',()=>{for(const status of [202,200]){TestBed.inject(AdminPedidosApiService).cancel('PED-one').subscribe();const req=http.expectOne('/api/java/pedidos/PED-one/anulacion');expect(req.request.body).toBeNull();req.flush(envelope({pedidoId:'PED-one',estado:status===200?'ANULADO':'COMPENSANDO'}),{status,statusText:'OK'});}});
 it('anulación 409 no se interpreta como éxito',()=>{let failed=false;TestBed.inject(AdminPedidosApiService).cancel('PED-one').subscribe({error:()=>failed=true});http.expectOne('/api/java/pedidos/PED-one/anulacion').flush({}, {status:409,statusText:'Conflict'});expect(failed).toBeTrue();});
 it('acepta XLSX sin parsear su contenido',()=>expect(validateFile(new File(['bytes'],'pedidos.XLSX'),10485760)).toBeNull());
 it('rechaza extensión, ausencia, vacío y exceso de tamaño',()=>{expect(validateFile(new File(['x'],'datos.csv'),100)).toContain('.xlsx');expect(validateFile(null,100)).toBeTruthy();expect(validateFile(new File([],'datos.xlsx'),100)).toContain('vacío');expect(validateFile(new File(['123'],'datos.xlsx'),2)).toContain('límite');});
 it('POST multipart usa archivo y hereda interceptor sin fijar Content-Type',()=>{const file=new File(['x'],'datos.xlsx');TestBed.inject(AdminCargasApiService).upload(file).subscribe();const req=http.expectOne('/api/cargas/cargas');expect(req.request.body instanceof FormData).toBeTrue();expect(req.request.body.get('archivo') instanceof File).toBeTrue();expect(req.request.body.get('archivo').name).toBe(file.name);expect(req.request.body.get('archivo').size).toBe(file.size);expect(req.request.headers.has('Content-Type')).toBeFalse();expect(req.request.headers.get('X-Host-Test')).toBe('inherited');req.flush(envelope({cargaId:'CG-test'}),{status:202,statusText:'Accepted'});});
 it('202 guarda cargaId y un doble click no duplica upload',()=>{
  const fixture=TestBed.createComponent(LoadsComponent);const ui=fixture.componentInstance;ui.select(new File(['x'],'datos.xlsx'));ui.upload();ui.upload();
  http.expectOne('/api/cargas/cargas').flush(envelope({cargaId:'CG-test'}),{status:202,statusText:'Accepted'});http.expectOne('/api/cargas/cargas/CG-test').flush(envelope(carga('PROCESADA')));
  expect(TestBed.inject(RecentLoadsService).ids()).toEqual(['CG-test']);expect(ui.file()).toBeNull();fixture.destroy();
 });
 it('polling PROCESANDO espera 2 segundos entre solicitudes',fakeAsync(()=>{let calls=0;const sub=pollCarga(()=>{calls++;return of(carga());}).subscribe();expect(calls).toBe(1);tick(1999);expect(calls).toBe(1);tick(1);expect(calls).toBe(2);sub.unsubscribe();}));
 it('polling termina en PROCESADA',fakeAsync(()=>{let calls=0;pollCarga(()=>of(carga(++calls===1?'PROCESANDO':'PROCESADA'))).subscribe();tick(10000);expect(calls).toBe(2);}));
 it('polling termina en ERROR y cancelación del consumidor detiene temporizador',fakeAsync(()=>{let calls=0;pollCarga(()=>{calls++;return of(carga('ERROR'));}).subscribe();tick(10000);expect(calls).toBe(1);const sub=pollCarga(()=>{calls++;return of(carga());}).subscribe();sub.unsubscribe();tick(10000);expect(calls).toBe(2);}));
 it('recent loads persiste solo 10 IDs únicos en clave separada',()=>{const recent=TestBed.inject(RecentLoadsService);storage.setItem('host-auth','sentinel');for(let i=0;i<12;i++)recent.add('CG-'+i);recent.add('CG-11');expect(recent.ids().length).toBe(10);expect(new Set(recent.ids()).size).toBe(10);expect(JSON.parse(storage.getItem(RECENT_KEY)??'null')).toEqual(recent.ids());expect(storage.getItem(RECENT_KEY)).not.toContain('sentinel');expect(storage.getItem('host-auth')).toBe('sentinel');});
 it('GET reciente 404 retira ID local sin inventar un listado global',()=>{const recent=TestBed.inject(RecentLoadsService);recent.add('CG-test');TestBed.inject(AdminCargasApiService).known('CG-test').subscribe();http.expectOne('/api/cargas/cargas/CG-test').flush({}, {status:404,statusText:'Not Found'});expect(recent.ids()).toEqual([]);});
 it('reporte obtiene Blob autenticado y nombre de Content-Disposition',()=>{
  const blob=new Blob(['xlsx'],{type:'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'});
  TestBed.inject(AdminCargasApiService).report('CG-test').subscribe(r=>{expect(r.body).toBe(blob);expect(reportFilename(r.headers.get('Content-Disposition'),'CG-test')).toBe('resultado.xlsx');});
  const req=http.expectOne('/api/cargas/cargas/CG-test/reporte');expect(req.request.responseType).toBe('blob');expect(req.request.headers.get('X-Host-Test')).toBe('inherited');req.flush(blob,{headers:{'Content-Disposition':'attachment; filename="resultado.xlsx"'}});
 });
 it('reporte 409 muestra indisponibilidad sin intentar guardar archivo',()=>{const downloader=TestBed.inject(FileDownloader);spyOn(downloader,'save');const fixture=TestBed.createComponent(LoadsComponent);fixture.componentInstance.download(carga('PROCESADA'));http.expectOne('/api/cargas/cargas/CG-test/reporte').flush(new Blob(['{}']),{status:409,statusText:'Conflict'});expect(downloader.save).not.toHaveBeenCalled();expect(TestBed.inject(AdminFeedback).show).toHaveBeenCalledWith(jasmine.stringMatching('estado actual'),true);fixture.destroy();});
 it('errores 403/500 son seguros aunque el error sea un Blob',()=>{for(const status of [403,500]){const message=errorMessage(new HttpErrorResponse({status,error:new Blob(['secret stack'])}));expect(message).not.toContain('secret');expect(message.length).toBeGreaterThan(20);}});
 it('descarga revoca URL temporal y elimina enlace',fakeAsync(()=>{spyOn(URL,'createObjectURL').and.returnValue('blob:test');spyOn(URL,'revokeObjectURL');spyOn(HTMLAnchorElement.prototype,'click');TestBed.inject(FileDownloader).save(new Blob(['x']),'reporte.xlsx');tick();expect(URL.revokeObjectURL).toHaveBeenCalledWith('blob:test');expect(document.querySelector('a[href="blob:test"]')).toBeNull();}));
 it('nombre de reporte rechaza rutas y soporta filename UTF8',()=>{expect(reportFilename('attachment; filename="../mal.xlsx"','CG-test')).toBe('reporte-CG-test.xlsx');expect(reportFilename("attachment; filename*=UTF-8''informe%20final.xlsx",'CG-test')).toBe('informe final.xlsx');});
 it('progreso es desconocido sin filas y deriva resultados cuando hay total',()=>{expect(progressOf(carga())).toBeNull();expect(progressOf({...carga(),totales:{filas:10,aceptadas:2,rechazadas:1,duplicadas:2}})).toBe(50);});
});
describe('Navegación del remoto',()=>{
 it('montado bajo admin redirige a dashboard con subnav y sin duplicar shell',async()=>{
  TestBed.configureTestingModule({providers:[provideRouter([{path:'admin',children:ADMIN_ROUTES}]),provideHttpClient(),provideHttpClientTesting(),provideNoopAnimations(),{provide:RECENT_STORAGE,useValue:new MemoryStorage()}]});
  const harness=await RouterTestingHarness.create();await harness.navigateByUrl('/admin');TestBed.inject(HttpTestingController).expectOne('/api/java/pedidos?pagina=0').flush(envelope([]));harness.detectChanges();
  expect(TestBed.inject(Router).url).toBe('/admin/dashboard');expect(harness.routeNativeElement?.textContent).toContain('Dashboard');expect(harness.routeNativeElement?.querySelector('nav')?.getAttribute('aria-label')).toBe('Secciones de administración');expect(harness.routeNativeElement?.querySelector('mat-sidenav')).toBeNull();
  TestBed.inject(HttpTestingController).verify();
 });
});
