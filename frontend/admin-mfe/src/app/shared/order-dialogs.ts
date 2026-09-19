import { Component, DestroyRef, inject, OnInit, signal } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { MAT_DIALOG_DATA, MatDialogModule } from '@angular/material/dialog';
import { finalize } from 'rxjs';
import { AdminPedidosApiService } from '../core/api';
import { PedidoDetalleAdmin } from '../core/models';
import { errorMessage } from '../core/presentation';
import { UI } from './ui';
import { AdminStatus } from './status';
export interface Confirmation {action:'retry'|'cancel';id:string;}
@Component({standalone:true,imports:[...UI,MatDialogModule],template:`
<h2 mat-dialog-title>{{data.action==='retry'?'¿Reintentar pedido?':'¿Solicitar anulación?'}}</h2><mat-dialog-content><p class="adm-id">{{data.id}}</p>
@if(data.action==='retry'){<p>El worker retomará el pedido desde el punto pendiente. El cambio de estado puede tardar unos momentos.</p>}
@else{<p>Esta solicitud puede iniciar compensación de las operaciones realizadas. Si el stock ya se confirmó, el pedido puede volver a Requiere revisión.</p>}
</mat-dialog-content><mat-dialog-actions align="end"><button mat-button [mat-dialog-close]="false">Volver</button><button mat-flat-button [color]="data.action==='cancel'?'warn':'primary'" [mat-dialog-close]="true">{{data.action==='retry'?'Reintentar':'Solicitar anulación'}}</button></mat-dialog-actions>`})
export class ConfirmOrderDialog {readonly data=inject<Confirmation>(MAT_DIALOG_DATA);}
@Component({standalone:true,imports:[...UI,MatDialogModule,AdminStatus],template:`
<h2 mat-dialog-title>Detalle del pedido</h2><mat-dialog-content class="admin-mfe adm-dialog"><p class="adm-id">{{id}}</p>
@if(loading()){<mat-progress-bar mode="indeterminate" aria-label="Cargando detalle"/>}
@if(error()){<p class="adm-feedback adm-danger" role="alert">{{error()}}</p><button mat-button (click)="load()">Reintentar consulta</button>}
@if(order();as p){<admin-status [state]="p.estado"/><dl class="adm-facts"><div><dt>Almacén</dt><dd>{{p.almacenId}}</dd></div><div><dt>Subtotal</dt><dd>{{p.subtotal|number:'1.2-2'}}</dd></div><div><dt>Envío</dt><dd>{{p.envio===null?'Por calcular':(p.envio|number:'1.2-2')}}</dd></div><div><dt>Total</dt><dd>{{p.total===null?'Por calcular':(p.total|number:'1.2-2')}}</dd></div></dl>
@if(p.correlationId){<p class="adm-muted adm-id">Correlación: {{p.correlationId}}</p>}
<h3>Pasos del despacho</h3>@if(!p.pasos.length){<p class="adm-muted">Aún no hay pasos registrados.</p>}@else{<div class="adm-table-scroll"><table><thead><tr><th>Paso</th><th>Estado</th><th>Intentos</th><th>Duración</th></tr></thead><tbody>@for(s of p.pasos;track $index){<tr><td>{{s.paso}}</td><td><admin-status [state]="s.estado"/></td><td>{{s.intentos}}</td><td>{{s.ms===null?'Pendiente':s.ms+' ms'}}</td></tr>}</tbody></table></div>}
<h3>Compensaciones</h3>@if(!p.compensaciones.length){<p class="adm-muted">No se registran compensaciones.</p>}@else{@for(s of p.compensaciones;track $index){<p>{{s.paso}} · {{s.estado}} · {{s.intentos}} intentos · {{s.ms===null?'Duración pendiente':s.ms+' ms'}}</p>}}
<h3>Guía</h3><p>{{p.guia?p.guia.id+' · '+p.guia.estado:'Todavía no hay una guía disponible.'}}</p>
}
</mat-dialog-content><mat-dialog-actions align="end"><button mat-button mat-dialog-close>Cerrar</button></mat-dialog-actions>`})
export class OrderDetailDialog implements OnInit {
 readonly id=inject<string>(MAT_DIALOG_DATA);private api=inject(AdminPedidosApiService);private destroy=inject(DestroyRef);
 order=signal<PedidoDetalleAdmin|null>(null);loading=signal(false);error=signal('');
 ngOnInit(){this.load();}
 load(){if(this.loading())return;this.loading.set(true);this.error.set('');this.api.detail(this.id).pipe(takeUntilDestroyed(this.destroy),finalize(()=>this.loading.set(false))).subscribe({next:p=>this.order.set(p),error:e=>this.error.set(errorMessage(e))});}
}
