import { inject, Injectable } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { map } from 'rxjs';
import { CONFIG } from './config';
import { AuthResponse, Envelope, Order, OrderDetail, OrderInput, OrderSummary, Product, ProductInput, Stock } from './models';
@Injectable({providedIn:'root'})
export class AuthApiService {
  private http=inject(HttpClient); private base=inject(CONFIG).javaApi;
  login(usuario:string,clave:string) { return this.http.post<Envelope<AuthResponse>>(`${this.base}/auth/login`,{usuario,clave}).pipe(map(r=>r.data)); }
  refresh(refreshToken:string) { return this.http.post<Envelope<AuthResponse>>(`${this.base}/auth/refresh`,{refreshToken}).pipe(map(r=>r.data)); }
  logout(refreshToken:string) { return this.http.post<Envelope<{revocado:boolean}>>(`${this.base}/auth/logout`,{refreshToken}); }
}
@Injectable({providedIn:'root'})
export class ProductosApiService {
  private http=inject(HttpClient); private base=inject(CONFIG).javaApi;
  list(pagina=0) { return this.http.get<Envelope<Product[]>>(`${this.base}/productos`,{params:{pagina}}).pipe(map(r=>r.data)); }
  create(p:ProductInput) { const {sku,nombre,precio,peso}=p; return this.http.post<Envelope<Product>>(`${this.base}/productos`,{sku,nombre,precio,peso}).pipe(map(r=>r.data)); }
  update(sku:string,p:Omit<ProductInput,'sku'>) { const {nombre,precio,peso}=p; return this.http.put<Envelope<Product>>(`${this.base}/productos/${encodeURIComponent(sku)}`,{nombre,precio,peso}).pipe(map(r=>r.data)); }
  stock(sku:string,almacenId:string) { return this.http.get<Envelope<Stock>>(`${this.base}/productos/${encodeURIComponent(sku)}/stock`,{params:{almacenId}}).pipe(map(r=>r.data)); }
  updateStock(sku:string,almacenId:string,disponible:number) { return this.http.put<Envelope<Stock>>(`${this.base}/productos/${encodeURIComponent(sku)}/stock`,{disponible},{params:{almacenId}}).pipe(map(r=>r.data)); }
}
@Injectable({providedIn:'root'})
export class PedidosApiService {
  private http=inject(HttpClient); private base=inject(CONFIG).javaApi;
  list(pagina=0) { return this.http.get<Envelope<Order[]>>(`${this.base}/pedidos`,{params:{pagina}}).pipe(map(r=>r.data)); }
  detail(id:string) { return this.http.get<Envelope<OrderDetail>>(`${this.base}/pedidos/${encodeURIComponent(id)}`).pipe(map(r=>r.data)); }
  create(p:OrderInput) { const {solicitudId,almacenId,zonaEntrega}=p; const items=p.items.map(({sku,cantidad})=>({sku,cantidad})); return this.http.post<Envelope<OrderSummary>>(`${this.base}/pedidos`,{solicitudId,almacenId,zonaEntrega,items}).pipe(map(r=>r.data)); }
  cancel(id:string) { return this.http.post<Envelope<OrderSummary>>(`${this.base}/pedidos/${encodeURIComponent(id)}/anulacion`,{}).pipe(map(r=>r.data)); }
}
