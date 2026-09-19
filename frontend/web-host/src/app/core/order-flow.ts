import { inject, Injectable } from '@angular/core';
import { defer, expand, EMPTY, Observable, switchMap, timer } from 'rxjs';
import { SESSION_STORAGE } from './config';
import { SessionService } from './session';
import { PedidosApiService } from './api';
import { DeliveryZone, OrderDetail, OrderInput, OrderState, Product } from './models';
export const activeOrder=(state:OrderState)=>['RECIBIDO','EN_PROCESO','COMPENSANDO'].includes(state);
export function pollOrder(fetch:()=>Observable<OrderDetail>,delay=2500):Observable<OrderDetail>{
 return defer(fetch).pipe(expand(order=>activeOrder(order.estado)?timer(delay).pipe(switchMap(fetch)):EMPTY));
}
// No mapping is inferred from SKUs, seed users, or free-text warehouse input.
@Injectable({providedIn:'root'})
export class WarehouseResolver { resolve(product:Product):string|null { return product.almacenId && /^ALM-\d{2}$/.test(product.almacenId) ? product.almacenId : null; } }
@Injectable()
export class OrderDraft {
 private api=inject(PedidosApiService);
 private storage=inject(SESSION_STORAGE); private key='pedidos.draft.'+inject(SessionService).user()?.id;
 private intent?:OrderInput;
 constructor(){try{const raw=this.storage.getItem(this.key);if(raw){const value:OrderInput=JSON.parse(raw);if(value.solicitudId&&value.almacenId&&Array.isArray(value.items))this.intent=value;}}catch{/* invalid local draft */}}
 get pending(){return this.intent!==undefined;}
 prepare(almacenId:string,zonaEntrega:DeliveryZone,items:{sku:string;cantidad:number}[]):OrderInput{
  if(!this.intent)this.intent={solicitudId:crypto.randomUUID(),almacenId,zonaEntrega,items:items.map(i=>({...i}))};
  try{this.storage.setItem(this.key,JSON.stringify(this.intent));}catch{/* retain in memory */}
  return structuredClone(this.intent);
 }
 submit(almacenId:string,zone:DeliveryZone,items:{sku:string;cantidad:number}[]){return this.api.create(this.prepare(almacenId,zone,items));}
 complete(){this.intent=undefined;try{this.storage.removeItem(this.key);}catch{/* storage unavailable */}}
}
