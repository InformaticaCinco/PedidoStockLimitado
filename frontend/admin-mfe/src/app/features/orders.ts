import { Component, computed, DestroyRef, inject, OnInit, signal, ViewContainerRef } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { FormBuilder, ReactiveFormsModule } from '@angular/forms';
import { ActivatedRoute, RouterLink } from '@angular/router';
import { MatDialog } from '@angular/material/dialog';
import { finalize, Observable } from 'rxjs';
import { AdminCargasApiService, AdminPedidosApiService, countsOf, filterOrders } from '../core/api';
import { Carga, EstadoPedido, PedidoAdmin } from '../core/models';
import { AdminFeedback, errorMessage } from '../core/presentation';
import { RecentLoadsService } from '../core/recent-loads';
import { UI } from '../shared/ui';
import { AdminStatus } from '../shared/status';
import { ConfirmOrderDialog, OrderDetailDialog } from '../shared/order-dialogs';
@Component({standalone:true,imports:[...UI,ReactiveFormsModule,AdminStatus,RouterLink],template:`
<div class="adm-heading"><div><p class="adm-eyebrow">{{review?'ATENCIÓN A EXCEPCIONES':'VISTA GENERAL'}}</p><h1>{{review?'Pedidos en revisión':'Dashboard'}}</h1><p class="adm-muted">{{review?'Revisa el proceso antes de decidir el siguiente paso.':'Una mirada a los pedidos y a la actividad de esta sesión.'}}</p></div><button mat-stroked-button (click)="load()" [disabled]="loading()"><lucide-icon name="refresh-cw" size="17"/> Actualizar</button></div>
@if(loading()){<mat-progress-bar mode="indeterminate" aria-label="Consultando pedidos"/><div class="adm-skeleton" aria-hidden="true"></div>}
@if(error()){<div class="adm-feedback adm-danger" role="alert"><p>{{error()}}</p><button mat-button (click)="load()">Reintentar consulta</button></div>}
@if(!review && loaded()){
<div class="adm-metrics"><article class="adm-metric"><span>Pedidos consultados</span><strong>{{orders().length}}</strong><small>Sobre los datos recuperados</small></article>@for(metric of metrics;track metric.state){<article class="adm-metric" [class.adm-accent-warning]="metric.state==='REQUIERE_REVISION'" [class.adm-accent-success]="metric.state==='DESPACHADO'"><span>{{metric.label}}</span><strong>{{counts()[metric.state]}}</strong></article>}</div>
<section class="adm-session-load"><div><h2>Carga reciente de esta sesión</h2>@if(recentLoad();as c){<p class="adm-id">{{c.cargaId}}</p><admin-status [state]="c.estado"/>}@else if(loadError()){<p class="adm-muted">No se pudo consultar la carga reciente. Puedes reintentar desde Carga masiva.</p>}@else if(recent.ids().length){<p class="adm-muted">Consultando carga reciente…</p>}@else{<p class="adm-muted">Sin carga activa en esta sesión</p>}</div><a mat-stroked-button routerLink="../cargas"><lucide-icon name="upload" size="17"/> Ir a carga masiva</a></section>
}
@if(limited()){<p class="adm-feedback adm-warning" role="status">Se alcanzó el límite de consulta. Los resultados y métricas corresponden solo a los pedidos recuperados, no al total global.</p>}
@if(loaded()){
<div class="adm-filters"><mat-form-field appearance="outline"><mat-label>Buscar pedido</mat-label><input matInput [formControl]="search" placeholder="ID de pedido"/><lucide-icon matSuffix name="search" size="18"/></mat-form-field>@if(!review){<mat-form-field appearance="outline"><mat-label>Estado</mat-label><mat-select [formControl]="state"><mat-option value="">Todos</mat-option>@for(metric of metrics;track metric.state){<mat-option [value]="metric.state">{{metric.label}}</mat-option>}</mat-select></mat-form-field>}<span class="adm-muted">{{visible().length}} resultados</span></div>
@if(!visible().length){<section class="adm-empty"><span class="adm-empty-icon"><lucide-icon [name]="review?'circle-check':'package-search'" size="30"/></span><h2>{{review?'No hay pedidos en revisión':'No hay pedidos para mostrar'}}</h2><p>{{review?'No se encontraron pedidos en REQUIERE_REVISION entre los datos consultados.':'Cuando existan pedidos que coincidan con tu búsqueda, aparecerán aquí.'}}</p></section>}
@else{<div class="adm-table-scroll"><table><thead><tr><th>Pedido</th><th>Estado</th><th>Total</th><th>Acciones</th></tr></thead><tbody>@for(p of visible();track p.pedidoId){<tr><td><span class="adm-id">{{p.pedidoId}}</span><small>{{p.almacenId}}</small>@if(review && p.correlationId){<small class="adm-id">Correlación: {{p.correlationId}}</small>}</td><td><admin-status [state]="p.estado"/></td><td>{{p.total===null?'Por calcular':(p.total|number:'1.2-2')}}</td><td><div class="adm-actions"><button mat-button color="primary" (click)="detail(p)">Ver detalle</button>@if(review){<button mat-stroked-button color="primary" [disabled]="busy()" (click)="confirm(p,'retry')">Reintentar</button><button mat-button color="warn" [disabled]="busy()||p.anulacionSolicitada" (click)="confirm(p,'cancel')">Anular</button>}</div></td></tr>}</tbody></table></div>}
}
`})
export class OrdersComponent implements OnInit {
 private api=inject(AdminPedidosApiService);private cargas=inject(AdminCargasApiService);private dialog=inject(MatDialog);private view=inject(ViewContainerRef);private destroy=inject(DestroyRef);private feedback=inject(AdminFeedback);private fb=inject(FormBuilder);
 readonly recent=inject(RecentLoadsService);readonly review=inject(ActivatedRoute).snapshot.data['review']===true;
 loading=signal(false);loaded=signal(false);error=signal('');limited=signal(false);orders=signal<PedidoAdmin[]>([]);busy=signal(false);
 recentLoad=signal<Carga|null>(null);loadError=signal(false);search=this.fb.nonNullable.control('');state=this.fb.nonNullable.control<EstadoPedido|''>('');query=signal('');filter=signal<EstadoPedido|''>('');
 counts=computed(()=>countsOf(this.orders()));visible=computed(()=>filterOrders(this.orders(),this.query(),this.review?'REQUIERE_REVISION':this.filter()));
 metrics:{state:EstadoPedido;label:string}[]=[{state:'RECIBIDO',label:'Recibidos'},{state:'EN_PROCESO',label:'En proceso'},{state:'COMPENSANDO',label:'Compensando'},{state:'DESPACHADO',label:'Despachados'},{state:'ANULADO',label:'Anulados'},{state:'REQUIERE_REVISION',label:'Requieren revisión'}];
 ngOnInit(){this.search.valueChanges.pipe(takeUntilDestroyed(this.destroy)).subscribe(q=>this.query.set(q));this.state.valueChanges.pipe(takeUntilDestroyed(this.destroy)).subscribe(s=>this.filter.set(s));this.load();if(!this.review){const id=this.recent.ids()[0];if(id)this.cargas.known(id).pipe(takeUntilDestroyed(this.destroy)).subscribe({next:c=>this.recentLoad.set(c),error:()=>this.loadError.set(true)});}}
 load(){if(this.loading())return;this.loading.set(true);this.error.set('');this.api.all().pipe(takeUntilDestroyed(this.destroy),finalize(()=>this.loading.set(false))).subscribe({next:s=>{this.orders.set(s.pedidos);this.limited.set(s.limited);this.loaded.set(true);},error:e=>this.error.set(errorMessage(e))});}
 detail(p:PedidoAdmin){this.dialog.open(OrderDetailDialog,{data:p.pedidoId,width:'760px',maxWidth:'95vw',viewContainerRef:this.view});}
 confirm(p:PedidoAdmin,action:'retry'|'cancel'){
  if(this.busy())return;this.busy.set(true);
  this.dialog.open(ConfirmOrderDialog,{data:{id:p.pedidoId,action},width:'460px',maxWidth:'95vw',viewContainerRef:this.view}).afterClosed().pipe(takeUntilDestroyed(this.destroy)).subscribe(yes=>{
   if(!yes){this.busy.set(false);return;}
   const request:Observable<unknown>=action==='retry'?this.api.retry(p.pedidoId):this.api.cancel(p.pedidoId);
   request.pipe(takeUntilDestroyed(this.destroy),finalize(()=>this.busy.set(false))).subscribe({next:()=>{this.feedback.show(action==='retry'?'Reintento aceptado. El worker retomará el pedido; el estado puede tardar en cambiar.':'Solicitud de anulación recibida. La compensación puede requerir revisión.');this.load();},error:e=>{this.feedback.show(errorMessage(e),true);this.load();}});
  });
 }
}
