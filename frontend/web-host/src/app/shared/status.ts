import { Component, Input } from '@angular/core';
@Component({selector:'app-status',standalone:true,template:`<span class="status" [class.success]="state==='DESPACHADO' || state==='COMPLETADO'" [class.warning]="state==='REQUIERE_REVISION' || state==='COMPENSANDO'" [class.critical]="state==='ANULADO' || state==='ERROR'">{{label}}</span>`})
export class StatusComponent {
 @Input({required:true}) state='';
 get label(){const labels:Record<string,string>={RECIBIDO:'Recibido',EN_PROCESO:'En proceso',DESPACHADO:'Despachado',COMPENSANDO:'Compensando',ANULADO:'Anulado',REQUIERE_REVISION:'Requiere revisión',COMPLETADO:'Completado',ERROR:'Error',PENDIENTE:'Pendiente'};return labels[this.state]??this.state;}
}
