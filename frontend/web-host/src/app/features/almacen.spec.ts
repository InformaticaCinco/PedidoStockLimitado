import { importProvidersFrom } from '@angular/core';
import { TestBed } from '@angular/core/testing';
import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { provideNoopAnimations } from '@angular/platform-browser/animations';
import { provideRouter, Router } from '@angular/router';
import { MAT_DIALOG_DATA, MatDialogModule, MatDialogRef } from '@angular/material/dialog';
import { LucideAngularModule, Plus, Info, RefreshCw, Search, Package, PackageSearch, CircleAlert, CircleHelp, Pencil, X } from 'lucide-angular';
import { ProductsComponent } from './products';
import { StockDialog } from './stock-dialog';
import { SessionService } from '../core/session';
import { SESSION_STORAGE } from '../core/config';
import { Notifications } from '../core/errors';
import { Product, Role } from '../core/models';

const product=(sku:string,almacenId:string|null,vendedorId='VEN-1'):Product=>({sku,almacenId,vendedorId,nombre:sku,precio:12,peso:1});
const first=product('SKU-00042','ALM-07');
const other=product('SKU-00043','ALM-19','VEN-2');
const wrapped=<T>(data:T)=>({code:200,statusCode:'HTTP_200_OK',message:'OK',data});
const stock=(p:Product)=>({sku:p.sku,almacenId:p.almacenId,disponible:9,reservado:2,total:11});
function setup(role:Role='COMPRADOR',data:Product=first,ref:{close:(value?:unknown)=>void;disableClose?:boolean}={close:()=>undefined}){
 sessionStorage.clear();
 TestBed.configureTestingModule({imports:[ProductsComponent,StockDialog],providers:[provideRouter([]),provideHttpClient(),provideHttpClientTesting(),provideNoopAnimations(),
  importProvidersFrom(MatDialogModule,LucideAngularModule.pick({Plus,Info,RefreshCw,Search,Package,PackageSearch,CircleAlert,CircleHelp,Pencil,X})),
  {provide:SessionService,useValue:{user:()=>({id:'VEN-1',nombre:'Demo',rol:role})}},
  {provide:SESSION_STORAGE,useValue:sessionStorage},
  {provide:MAT_DIALOG_DATA,useValue:data},{provide:MatDialogRef,useValue:ref},
  {provide:Notifications,useValue:{show:jasmine.createSpy('notify')}}]});
 spyOn(TestBed.inject(Router),'navigate').and.resolveTo(true);
 return TestBed.inject(HttpTestingController);
}
function catalog(http:HttpTestingController,products:Product[]){
 const fixture=TestBed.createComponent(ProductsComponent);fixture.detectChanges();http.expectOne('/api/java/productos?pagina=0').flush(wrapped(products));
 http.match(r=>r.url.endsWith('/stock')).forEach(r=>r.flush(wrapped(stock(products.find(p=>r.request.url.includes(p.sku))!))));
 fixture.detectChanges();return fixture;
}
describe('Almacén real de producto en comprador',()=>{
 let http:HttpTestingController;
 beforeEach(()=>http=setup());afterEach(()=>{http.verify();sessionStorage.clear();});
 it('habilita crear pedido y envía almacén recibido, sin clienteId ni IdUsuario; retry estable',()=>{
  const fixture=catalog(http,[first]);const ui=fixture.componentInstance;ui.select(first);fixture.detectChanges();
  const confirm=[...fixture.nativeElement.querySelectorAll('button')].find((b:HTMLButtonElement)=>b.textContent?.includes('Confirmar pedido')) as HTMLButtonElement;
  expect(confirm.disabled).toBeFalse();confirm.click();
  const req=http.expectOne('/api/java/pedidos');const body=req.request.body;
  expect(body.almacenId).toBe('ALM-07');expect(Object.keys(body).sort()).toEqual(['almacenId','items','solicitudId','zonaEntrega']);
  expect(body.items).toEqual([{sku:'SKU-00042',cantidad:1}]);
  req.flush({}, {status:503,statusText:'Unavailable'});ui.submit();
  const retry=http.expectOne('/api/java/pedidos');expect(retry.request.body).toEqual(body);
  retry.flush(wrapped({pedidoId:'PED-created',estado:'RECIBIDO'}),{status:202,statusText:'Accepted'});
  expect(ui.selected()).toEqual([]);expect(ui.draft.pending).toBeFalse();expect(TestBed.inject(Router).navigate).toHaveBeenCalledWith(['/comprador/pedidos','PED-created']);fixture.destroy();
 });
 it('impide mezclar almacenes y muestra mensaje claro en UI',()=>{
  const fixture=catalog(http,[first,other]);const buttons=fixture.nativeElement.querySelectorAll('.product-action button') as NodeListOf<HTMLButtonElement>;
  buttons[0].click();buttons[1].click();fixture.detectChanges();
  expect(fixture.componentInstance.selected().map(p=>p.sku)).toEqual([first.sku]);
  expect(fixture.componentInstance.warehouse()).toBe('ALM-07');
  expect(fixture.nativeElement.querySelector('[role="alert"]').textContent).toContain('No puedes mezclar productos de almacenes diferentes');fixture.destroy();
 });
 it('acepta varias líneas del mismo almacén y permite cambiar al vaciar selección',()=>{
  const second=product('SKU-00044','ALM-07');const fixture=catalog(http,[first,second,other]);const ui=fixture.componentInstance;
  ui.select(first);ui.select(second);expect(ui.selected().length).toBe(2);expect(ui.warehouse()).toBe('ALM-07');
  ui.remove(first.sku);ui.remove(second.sku);ui.select(other);expect(ui.warehouse()).toBe('ALM-19');fixture.destroy();
 });
 it('relación ausente no inventa almacén ni permite enviar',()=>{
  const missing=product('SKU-00045',null);const fixture=catalog(http,[missing]);const ui=fixture.componentInstance;ui.select(missing);ui.submit();
  expect(ui.selected().length).toBe(0);expect(ui.warehouse()).toBeNull();http.expectNone('/api/java/pedidos');fixture.destroy();
 });
});
describe('Stock vendedor por almacén de producto',()=>{
 let http:HttpTestingController;
 afterEach(()=>{http.verify();sessionStorage.clear();});
 it('catálogo consulta stock propio con el almacén recibido, no el de otro vendedor',()=>{
  http=setup('VENDEDOR');
  const fixture=TestBed.createComponent(ProductsComponent);fixture.detectChanges();http.expectOne('/api/java/productos?pagina=0').flush(wrapped([first,other]));
  const req=http.expectOne('/api/java/productos/SKU-00042/stock?almacenId=ALM-07');req.flush(wrapped(stock(first)));
  http.expectNone('/api/java/productos/SKU-00043/stock?almacenId=ALM-19');fixture.detectChanges();
  expect(fixture.nativeElement.textContent).toContain('Disponible: 9');expect(fixture.componentInstance.visible().length).toBe(1);fixture.destroy();
 });
 it('diálogo consulta y actualiza usando almacén del producto sin campo manual ni identidad',()=>{
  const p=product('SKU-00046','ALM-19');const ref={close:jasmine.createSpy('close'),disableClose:false};
  http=setup('VENDEDOR',p,ref);
  const fixture=TestBed.createComponent(StockDialog);fixture.detectChanges();
  http.expectOne('/api/java/productos/SKU-00046/stock?almacenId=ALM-19').flush(wrapped(stock(p)));fixture.detectChanges();
  expect(fixture.nativeElement.querySelectorAll('input').length).toBe(1);
  fixture.componentInstance.form.setValue({disponible:7});fixture.componentInstance.save();fixture.componentInstance.save();
  const req=http.expectOne('/api/java/productos/SKU-00046/stock?almacenId=ALM-19');expect(req.request.method).toBe('PUT');expect(req.request.body).toEqual({disponible:7});
  req.flush(wrapped({...stock(p),disponible:7,total:9}));expect(ref.close).toHaveBeenCalledWith({...stock(p),disponible:7,total:9});fixture.destroy();
 });
 it('rechaza stock negativo o fraccionario sin enviar PUT',()=>{
  http=setup('VENDEDOR');
  const fixture=TestBed.createComponent(StockDialog);fixture.detectChanges();http.expectOne('/api/java/productos/SKU-00042/stock?almacenId=ALM-07').flush(wrapped(stock(first)));
  for(const disponible of [-1,1.5,1000000001]){fixture.componentInstance.form.setValue({disponible});fixture.componentInstance.save();expect(fixture.componentInstance.form.invalid).toBeTrue();}
  http.expectNone(r=>r.method==='PUT');fixture.destroy();
 });
});
