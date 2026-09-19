import { inject, Injectable } from '@angular/core';
import { HttpClient, HttpErrorResponse } from '@angular/common/http';
import { catchError, defer, EMPTY, expand, map, Observable, reduce, switchMap, throwError, timer } from 'rxjs';
import { ADMIN_CONFIG } from './config';
import { AnulacionResponse, ApiEnvelope, Carga, EstadoPedido, PedidoAdmin, PedidoDetalleAdmin, PedidoSnapshot, ReintentoResponse } from './models';
import { RecentLoadsService } from './recent-loads';
export function countsOf(rows:PedidoAdmin[]):Record<EstadoPedido,number>{const counts:Record<EstadoPedido,number>={RECIBIDO:0,EN_PROCESO:0,DESPACHADO:0,ANULADO:0,COMPENSANDO:0,REQUIERE_REVISION:0};for(const p of rows)if(p.estado in counts)counts[p.estado]++;return counts;}
export function filterOrders(rows:PedidoAdmin[],query:string,state:EstadoPedido|''):PedidoAdmin[]{return rows.filter(p=>(!state||p.estado===state)&&p.pedidoId.toLowerCase().includes(query.trim().toLowerCase()));}
@Injectable({providedIn:'root'})
export class AdminPedidosApiService {
 private http=inject(HttpClient);private config=inject(ADMIN_CONFIG);
 page(pagina:number){return this.http.get<ApiEnvelope<PedidoAdmin[]>>(`${this.config.javaApi}/pedidos`,{params:{pagina}}).pipe(map(r=>r.data));}
 all():Observable<PedidoSnapshot>{return defer(()=>{let pages=0;let limited=false;const max=Math.max(1,Math.min(1000,Math.floor(this.config.maxOrderPages)||100));return this.page(0).pipe(expand(rows=>{pages++;if(rows.length<50)return EMPTY;if(pages>=max){limited=true;return EMPTY;}return this.page(pages);}),reduce((rows:PedidoAdmin[],page)=>[...rows,...page],[]),map(rows=>({pedidos:[...new Map(rows.map(p=>[p.pedidoId,p])).values()],limited,pages})));});}
 detail(id:string){return this.http.get<ApiEnvelope<PedidoDetalleAdmin>>(`${this.config.javaApi}/pedidos/${encodeURIComponent(id)}`).pipe(map(r=>r.data));}
 retry(id:string){return this.http.post<ApiEnvelope<ReintentoResponse>>(`${this.config.despachosApi}/despachos/${encodeURIComponent(id)}/reintento`,null).pipe(map(r=>r.data));}
 cancel(id:string){return this.http.post<ApiEnvelope<AnulacionResponse>>(`${this.config.javaApi}/pedidos/${encodeURIComponent(id)}/anulacion`,null).pipe(map(r=>r.data));}
}
export function pollCarga(fetch:()=>Observable<Carga>,interval=2000):Observable<Carga>{return defer(fetch).pipe(expand(c=>c.estado==='PROCESANDO'?timer(interval).pipe(switchMap(fetch)):EMPTY));}
@Injectable({providedIn:'root'})
export class AdminCargasApiService {
 private http=inject(HttpClient);private config=inject(ADMIN_CONFIG);private recent=inject(RecentLoadsService);
 upload(file:File){const form=new FormData();form.append('archivo',file,file.name);return this.http.post<ApiEnvelope<{cargaId:string}>>(`${this.config.cargasApi}/cargas`,form).pipe(map(r=>r.data));}
 get(id:string){return this.http.get<ApiEnvelope<Carga>>(`${this.config.cargasApi}/cargas/${encodeURIComponent(id)}`).pipe(map(r=>r.data));}
 known(id:string){return this.get(id).pipe(catchError((e:unknown)=>{if(e instanceof HttpErrorResponse&&e.status===404){this.recent.remove(id);return EMPTY;}return throwError(()=>e);}));}
 watch(id:string){return pollCarga(()=>this.known(id));}
 report(id:string){return this.http.get(`${this.config.cargasApi}/cargas/${encodeURIComponent(id)}/reporte`,{observe:'response',responseType:'blob'});}
}
