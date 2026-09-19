import { Component, Input } from '@angular/core';
@Component({selector:'admin-status',standalone:true,template:`<span class="adm-status" [class.adm-success]="state==='DESPACHADO'||state==='PROCESADA'||state==='COMPLETADO'" [class.adm-warning]="state==='REQUIERE_REVISION'||state==='COMPENSANDO'" [class.adm-danger]="state==='ERROR'||state==='ANULADO'||state==='FALLIDO'">{{label}}</span>`})
export class AdminStatus {
 @Input({required:true})state='';
 get label(){return ({RECIBIDO:'Recibido',EN_PROCESO:'En proceso',DESPACHADO:'Despachado',ANULADO:'Anulado',COMPENSANDO:'Compensando',REQUIERE_REVISION:'Requiere revisión',PROCESANDO:'Procesando',PROCESADA:'Procesada',ERROR:'Error',COMPLETADO:'Completado',FALLIDO:'Fallido'} as Record<string,string>)[this.state]??this.state;}
}
