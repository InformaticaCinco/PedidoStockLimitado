import { Component } from '@angular/core';
import { TestBed, fakeAsync, tick } from '@angular/core/testing';
import { HttpClient, HttpErrorResponse, provideHttpClient, withInterceptors } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { ActivatedRouteSnapshot, CanActivateFn, CanMatchFn, provideRouter, Router, RouterStateSnapshot, Routes, UrlTree } from '@angular/router';
import { RouterTestingHarness } from '@angular/router/testing';
import { firstValueFrom, of, Subject } from 'rxjs';
import { provideNoopAnimations } from '@angular/platform-browser/animations';
import { importProvidersFrom } from '@angular/core';
import { LucideAngularModule, Unplug, LoaderCircle, RefreshCw } from 'lucide-angular';
import { AuthApiService, PedidosApiService, ProductosApiService } from './api';
import { SESSION_KEY, SessionService } from './session';
import { SESSION_STORAGE } from './config';
import { sessionInterceptor } from './interceptor';
import { authGuard, roleGuard, adminCanMatch, menus } from './guards';
import { AuthResponse, Envelope, OrderDetail, Role, Session } from './models';
import { errorMessage } from './errors';
import { OrderDraft, pollOrder, WarehouseResolver } from './order-flow';
import { AdminComponent, REMOTE_LOADER } from '../features/admin';

const authValue=(role:Role='COMPRADOR',accessToken='access-1',refreshToken='refresh-1'):AuthResponse=>({accessToken,refreshToken,expiraEn:900,usuario:{id:'USR-test',nombre:'Demo',rol:role}});
const envelope=<T>(data:T):Envelope<T>=>({code:200,statusCode:'HTTP_200_OK',message:'OK',data});
const order=(estado:OrderDetail['estado']):OrderDetail=>({pedidoId:'PED-test',estado,almacenId:'ALM-01',subtotal:10,envio:null,total:null,pesoTotal:1,anulacionSolicitada:false,items:[],guia:null,pasos:[],compensaciones:[]});
class MemoryStorage implements Storage {
 private values=new Map<string,string>();get length(){return this.values.size;}clear(){this.values.clear();}getItem(k:string){return this.values.get(k)??null;}key(n:number){return [...this.values.keys()][n]??null;}removeItem(k:string){this.values.delete(k);}setItem(k:string,v:string){this.values.set(k,v);}
}

describe('Contratos, sesión y concurrencia',()=>{
 let http:HttpTestingController;let session:SessionService;let storage:MemoryStorage;
 beforeEach(()=>{storage=new MemoryStorage();TestBed.configureTestingModule({providers:[provideRouter([]),provideHttpClient(withInterceptors([sessionInterceptor])),provideHttpClientTesting(),{provide:SESSION_STORAGE,useValue:storage},OrderDraft]});http=TestBed.inject(HttpTestingController);session=TestBed.inject(SessionService);spyOn(TestBed.inject(Router),'navigateByUrl').and.resolveTo(true);});
 afterEach(()=>{session.ngOnDestroy();http.verify();});
 function login(role:Role='COMPRADOR'){session.login('demo','password').subscribe();http.expectOne('/api/java/auth/login').flush(envelope(authValue(role)));}
 it('login persiste usuario, tokens y expiración sin contraseña',()=>{login();const stored=JSON.parse(storage.getItem(SESSION_KEY)??'{}') as Session;expect(stored.usuario.rol).toBe('COMPRADOR');expect(stored.expiresAt).toBeGreaterThan(Date.now());expect(storage.getItem(SESSION_KEY)).not.toContain('password');});
 it('login inválido conserva sesión vacía y reporta error',()=>{let failed=false;session.login('x','bad').subscribe({error:()=>failed=true});http.expectOne('/api/java/auth/login').flush({}, {status:401,statusText:'Unauthorized'});expect(failed).toBeTrue();expect(session.session()).toBeNull();});
 it('restaura sesión persistida al recargar',()=>{storage.setItem(SESSION_KEY,JSON.stringify({...authValue(),expiresAt:Date.now()+900000}));session.restore();expect(session.user()?.id).toBe('USR-test');});
 it('descarta sesión persistida inválida',()=>{storage.setItem(SESSION_KEY,'{oops');session.restore();expect(session.session()).toBeNull();expect(storage.getItem(SESSION_KEY)).toBeNull();});
 it('logout limpia incluso si falla revocación',()=>{login();session.logout();expect(session.session()).toBeNull();const req=http.expectOne('/api/java/auth/logout');expect(req.request.body).toEqual({refreshToken:'refresh-1'});req.flush({}, {status:503,statusText:'Unavailable'});expect(storage.getItem(SESSION_KEY)).toBeNull();});
 it('agrega Bearer y conserva correlation id existente',()=>{login();TestBed.inject(HttpClient).get('/api/java/productos',{headers:{'X-Correlation-Id':'existing-id'}}).subscribe();const req=http.expectOne('/api/java/productos');expect(req.request.headers.get('Authorization')).toBe('Bearer access-1');expect(req.request.headers.get('X-Correlation-Id')).toBe('existing-id');req.flush({});});
 it('no filtra tokens a destinos externos',()=>{login();TestBed.inject(HttpClient).get('https://example.invalid/test').subscribe();const req=http.expectOne('https://example.invalid/test');expect(req.request.headers.has('Authorization')).toBeFalse();req.flush({});});
 it('rota access y refresh, reemplazando almacenamiento',()=>{login();session.refresh().subscribe();const r=http.expectOne('/api/java/auth/refresh');expect(r.request.body).toEqual({refreshToken:'refresh-1'});r.flush(envelope(authValue('COMPRADOR','access-2','refresh-2')));expect(session.session()?.refreshToken).toBe('refresh-2');expect(storage.getItem(SESSION_KEY)).not.toContain('refresh-1');});
 it('refresh single-flight comparte una sola solicitud concurrente',()=>{login();let n=0;session.refresh().subscribe(()=>n++);session.refresh().subscribe(()=>n++);http.expectOne('/api/java/auth/refresh').flush(envelope(authValue('COMPRADOR','access-2','refresh-2')));expect(n).toBe(2);});
 it('refresh fallido limpia y vuelve a login',()=>{login();session.refresh().subscribe({error:()=>undefined});http.expectOne('/api/java/auth/refresh').flush({}, {status:401,statusText:'Unauthorized'});expect(session.session()).toBeNull();expect(TestBed.inject(Router).navigateByUrl).toHaveBeenCalledWith('/login');});
 it('renueva antes de expirar mediante temporizador',fakeAsync(()=>{login();tick(870000);http.expectOne('/api/java/auth/refresh').flush(envelope(authValue('COMPRADOR','access-2','refresh-2')));expect(session.session()?.accessToken).toBe('access-2');session.ngOnDestroy();}));
 it('dos 401 concurrentes renuevan una vez y reintentan con token nuevo',()=>{login();const client=TestBed.inject(HttpClient);client.get('/api/java/a').subscribe();client.get('/api/java/b').subscribe();http.expectOne('/api/java/a').flush({}, {status:401,statusText:'Unauthorized'});http.expectOne('/api/java/b').flush({}, {status:401,statusText:'Unauthorized'});http.expectOne('/api/java/auth/refresh').flush(envelope(authValue('COMPRADOR','access-2','refresh-2')));for(const url of ['/api/java/a','/api/java/b']){const r=http.expectOne(url);expect(r.request.headers.get('Authorization')).toBe('Bearer access-2');r.flush({});}});
 it('un segundo 401 cierra sesión sin bucle de refresh',()=>{login();TestBed.inject(HttpClient).get('/api/java/a').subscribe({error:()=>undefined});http.expectOne('/api/java/a').flush({}, {status:401,statusText:'Unauthorized'});http.expectOne('/api/java/auth/refresh').flush(envelope(authValue('COMPRADOR','access-2','refresh-2')));http.expectOne('/api/java/a').flush({}, {status:401,statusText:'Unauthorized'});http.expectNone('/api/java/auth/refresh');expect(session.session()).toBeNull();});
 it('logout durante refresh revoca también el token rotado sin restaurar sesión',()=>{login();session.refresh().subscribe({error:()=>undefined});session.logout();http.expectOne('/api/java/auth/refresh').flush(envelope(authValue('COMPRADOR','access-2','refresh-2')));const revoke=http.match('/api/java/auth/logout');expect(revoke.map(r=>r.request.body.refreshToken)).toContain('refresh-2');revoke.forEach(r=>r.flush(envelope({revocado:true})));expect(session.session()).toBeNull();});
 it('auth guard exige sesión',()=>{const run=()=>TestBed.runInInjectionContext(()=>authGuard({} as ActivatedRouteSnapshot,{} as RouterStateSnapshot));expect((run() as UrlTree).toString()).toBe('/login');login();expect(run()).toBeTrue();});
 it('role guard impide otro rol',()=>{login('VENDEDOR');const guard=roleGuard('COMPRADOR');const result=TestBed.runInInjectionContext(()=>guard({} as ActivatedRouteSnapshot,{} as RouterStateSnapshot));expect((result as UrlTree).toString()).toBe('/vendedor/productos');});
 it('solicitudId y contenido estables ante timeout y recarga',()=>{login();const draft=TestBed.inject(OrderDraft);const a=draft.prepare('ALM-01','PROVINCIA',[{sku:'SKU-00002',cantidad:1}]);const b=draft.prepare('ALM-02','LIMA_PROVINCIA',[{sku:'SKU-00003',cantidad:2}]);expect(a).toEqual(b);const restored=TestBed.runInInjectionContext(()=>new OrderDraft());expect(restored.prepare('ALM-02','PROVINCIA',[])).toEqual(a);draft.complete();expect(draft.prepare('ALM-01','PROVINCIA',[]).solicitudId).not.toBe(a.solicitudId);});
 it('pedido envía solo campos permitidos sin cliente, precios ni usuario',()=>{const body={solicitudId:'sol-1',almacenId:'ALM-01',zonaEntrega:'PROVINCIA' as const,items:[{sku:'SKU-00002',cantidad:1,precio:7}],clienteId:'evil'};TestBed.inject(PedidosApiService).create(body).subscribe();const r=http.expectOne('/api/java/pedidos');expect(Object.keys(r.request.body).sort()).toEqual(['almacenId','items','solicitudId','zonaEntrega']);expect(r.request.body.items).toEqual([{sku:'SKU-00002',cantidad:1}]);r.flush(envelope({}));});
 it('anulación usa endpoint y body vacío, acepta 202',()=>{TestBed.inject(PedidosApiService).cancel('PED-test').subscribe();const r=http.expectOne('/api/java/pedidos/PED-test/anulacion');expect(r.request.method).toBe('POST');expect(r.request.body).toEqual({});r.flush(envelope({pedidoId:'PED-test'}),{status:202,statusText:'Accepted'});});
 it('productos nunca envían propietario en alta ni edición',()=>{const api=TestBed.inject(ProductosApiService);const product={sku:'SKU-00042',nombre:'Producto',precio:2,peso:1,vendedorId:'evil'};api.create(product).subscribe();const a=http.expectOne('/api/java/productos');expect(a.request.body.vendedorId).toBeUndefined();a.flush(envelope(product));api.update(product.sku,product).subscribe();const b=http.expectOne('/api/java/productos/SKU-00042');expect(Object.keys(b.request.body).sort()).toEqual(['nombre','peso','precio']);b.flush(envelope(product));});
 it('stock usa almacén proporcionado y solo disponible al actualizar',()=>{const api=TestBed.inject(ProductosApiService);api.stock('SKU-00042','ALM-02').subscribe();http.expectOne('/api/java/productos/SKU-00042/stock?almacenId=ALM-02').flush(envelope({}));api.updateStock('SKU-00042','ALM-02',5).subscribe();const r=http.expectOne('/api/java/productos/SKU-00042/stock?almacenId=ALM-02');expect(r.request.body).toEqual({disponible:5});r.flush(envelope({}));});
 it('no infiere almacén desde SKU o vendedor',()=>{expect(TestBed.inject(WarehouseResolver).resolve({sku:'SKU-00001',vendedorId:'USR-004',almacenId:null,nombre:'Producto',peso:1,precio:1})).toBeNull();});
});

describe('Estados y contratos de presentación',()=>{
 for(const code of [400,403,409])it(`error ${code} tiene mensaje seguro sin JSON técnico`,()=>{const message=errorMessage(new HttpErrorResponse({status:code,error:{stack:'secret'}}));expect(message.length).toBeGreaterThan(15);expect(message).not.toContain('secret');});
 it('menú contiene solo destinos del rol',()=>{expect(menus.COMPRADOR.map(m=>m.path)).toEqual(['/comprador/catalogo','/comprador/pedidos']);expect(menus.VENDEDOR.every(m=>m.path.startsWith('/vendedor/'))).toBeTrue();expect(menus.ADMIN.map(m=>m.path)).toEqual(['/admin']);});
 it('polling termina en estado final y no sigue solicitando',fakeAsync(()=>{let calls=0;const values:OrderDetail[]=[];pollOrder(()=>of(order(++calls===1?'EN_PROCESO':'DESPACHADO'))).subscribe(o=>values.push(o));tick(2500);tick(10000);expect(calls).toBe(2);expect(values.at(-1)?.estado).toBe('DESPACHADO');}));
 it('polling cancela temporizador al destruir consumidor',fakeAsync(()=>{let calls=0;const sub=pollOrder(()=>{calls++;return of(order('RECIBIDO'));}).subscribe();sub.unsubscribe();tick(10000);expect(calls).toBe(1);}));
});

@Component({standalone:true,template:''}) class BlankComponent {}
describe('Aislamiento del remoto ADMIN con el router real',()=>{
 for(const role of ['COMPRADOR','VENDEDOR','ADMIN'] as const)it(`${role}: canMatch decide antes de ejecutar loader`,async()=>{
  const load=jasmine.createSpy('remote route loader').and.resolveTo(BlankComponent);
  TestBed.configureTestingModule({providers:[{provide:SessionService,useValue:{user:()=>authValue(role).usuario}},provideRouter([{path:'admin',canMatch:[adminCanMatch],loadComponent:load},{path:'comprador/catalogo',component:BlankComponent},{path:'vendedor/productos',component:BlankComponent}])]});
  const harness=await RouterTestingHarness.create();await harness.navigateByUrl('/admin');expect(load.calls.count()).toBe(role==='ADMIN'?1:0);
 });
 it('remote ausente muestra fallback y reintenta sin romper la vista',async()=>{
  const loader=jasmine.createSpy('federation loader').and.rejectWith(Error('offline'));
  TestBed.configureTestingModule({imports:[AdminComponent],providers:[provideRouter([]),provideNoopAnimations(),{provide:REMOTE_LOADER,useValue:loader},importProvidersFrom(LucideAngularModule.pick({Unplug,LoaderCircle,RefreshCw}))]});
  const fixture=TestBed.createComponent(AdminComponent);fixture.detectChanges();await fixture.whenStable();fixture.detectChanges();expect(fixture.nativeElement.textContent).toContain('Módulo de administración no disponible');await fixture.componentInstance.retry();expect(loader.calls.count()).toBe(2);fixture.destroy();
 });
});
