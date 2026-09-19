import { Component, DestroyRef, inject, OnInit, signal } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { RouterLink } from '@angular/router';
import { finalize } from 'rxjs';
import { PedidosApiService } from '../core/api';
import { SessionService } from '../core/session';
import { Order } from '../core/models';
import { errorMessage } from '../core/errors';
import { UI } from '../shared/ui';
import { StatusComponent } from '../shared/status';
@Component({standalone:true,imports:[...UI,RouterLink,StatusComponent],template:`
<div class="page-heading"><div><p class="eyebrow">SEGUIMIENTO</p><h1>{{seller?'Pedidos recibidos':'Mis pedidos'}}</h1><p class="muted">{{seller?'Consulta únicamente las líneas de tus productos.':'Revisa el estado y el avance de tus pedidos.'}}</p></div><button mat-stroked-button (click)="load()" [disabled]="loading()"><lucide-icon name="refresh-cw" size="17"/> Actualizar</button></div>
@if(loading()){<mat-progress-bar mode="indeterminate" aria-label="Cargando pedidos"/><div class="skeleton" aria-hidden="true"></div>}
@else if(error()){<section class="empty" role="alert"><lucide-icon name="circle-alert"/><h2>No pudimos cargar los pedidos</h2><p>{{error()}}</p><button mat-stroked-button (click)="load()">Reintentar</button></section>}
@else if(!orders().length){<section class="empty"><span class="empty-icon"><lucide-icon name="package-search" size="32"/></span><h2>{{page()?'No hay más pedidos':'Todavía no hay pedidos'}}</h2><p>{{seller?'Los pedidos que incluyan tus productos aparecerán aquí.':'Explora el catálogo y encuentra productos para tu próximo pedido.'}}</p>@if(!seller){<a mat-flat-button color="primary" routerLink="/comprador/catalogo">Explorar catálogo</a>}</section>}
@else{<div class="table-scroll"><table><thead><tr><th>Pedido</th><th>Estado</th><th>{{seller?'Subtotal propio':'Subtotal'}}</th>@if(!seller){<th>Total</th>}<th>Detalle</th></tr></thead><tbody>@for(order of orders();track order.pedidoId){<tr><td><span class="order-id">{{order.pedidoId}}</span><small>{{order.items.length}} líneas · {{order.almacenId}}</small></td><td><app-status [state]="order.estado"/></td><td>{{order.subtotal|number:'1.2-2'}}</td>@if(!seller){<td>{{order.total===null?'Por calcular':(order.total|number:'1.2-2')}}</td>}<td><a mat-button color="primary" [routerLink]="[seller?'/vendedor/pedidos':'/comprador/pedidos',order.pedidoId]">Ver detalle <lucide-icon name="arrow-right" size="16"/></a></td></tr>}</tbody></table></div>}
<div class="pagination"><button mat-button [disabled]="page()===0||loading()" (click)="change(-1)">Anterior</button><span>Página {{page()+1}}</span><button mat-button [disabled]="orders().length<50||loading()" (click)="change(1)">Siguiente</button></div>`})
export class OrdersComponent implements OnInit {
 private api=inject(PedidosApiService);private destroy=inject(DestroyRef);seller=inject(SessionService).user()?.rol==='VENDEDOR';orders=signal<Order[]>([]);page=signal(0);loading=signal(false);error=signal('');
 ngOnInit(){this.load();}
 change(delta:number){this.page.update(p=>p+delta);this.load();}
 load(){if(this.loading())return;this.loading.set(true);this.error.set('');this.api.list(this.page()).pipe(takeUntilDestroyed(this.destroy),finalize(()=>this.loading.set(false))).subscribe({next:r=>this.orders.set(r),error:e=>this.error.set(errorMessage(e))});}
}
