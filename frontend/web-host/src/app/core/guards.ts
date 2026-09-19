import { inject } from '@angular/core';
import { CanActivateFn, CanMatchFn, Router } from '@angular/router';
import { SessionService, homeFor } from './session';
import { Role } from './models';
export const authGuard:CanActivateFn=()=>inject(SessionService).session()?true:inject(Router).parseUrl('/login');
export const roleGuard=(role:Role):CanActivateFn=>()=>{
 const user=inject(SessionService).user();return user?.rol===role?true:inject(Router).parseUrl(user?homeFor(user.rol):'/login');
};
export const adminCanMatch:CanMatchFn=()=>{
 const user=inject(SessionService).user();return user?.rol==='ADMIN'?true:inject(Router).parseUrl(user?homeFor(user.rol):'/login');
};
export interface MenuItem {label:string;path:string;icon:string;}
export const menus:Record<Role,MenuItem[]>={
 COMPRADOR:[{label:'Catálogo',path:'/comprador/catalogo',icon:'shopping-bag'},{label:'Mis pedidos',path:'/comprador/pedidos',icon:'package'}],
 VENDEDOR:[{label:'Productos',path:'/vendedor/productos',icon:'boxes'},{label:'Pedidos recibidos',path:'/vendedor/pedidos',icon:'package'}],
 ADMIN:[{label:'Administración',path:'/admin',icon:'layout-dashboard'}]
};
