import { InjectionToken } from '@angular/core';
export interface AdminConfig { javaApi:string; despachosApi:string; cargasApi:string; maxUploadBytes:number; maxOrderPages:number; }
declare global { interface Window { __PEDIDOS_CONFIG__?:Partial<AdminConfig>&{adminRemoteEntry?:string}; } }
export const ADMIN_CONFIG=new InjectionToken<AdminConfig>('Admin runtime config',{providedIn:'root',factory:()=>({javaApi:'/api/java',despachosApi:'/api/despachos',cargasApi:'/api/cargas',maxUploadBytes:10485760,maxOrderPages:100,...window.__PEDIDOS_CONFIG__})});
export const RECENT_STORAGE=new InjectionToken<Storage>('Recent load IDs storage',{providedIn:'root',factory:()=>sessionStorage});
