import { Routes } from '@angular/router';
import { inject } from '@angular/core';
import { Router } from '@angular/router';
import { authGuard, roleGuard, adminCanMatch } from './core/guards';
import { SessionService, homeFor } from './core/session';
export const routes:Routes=[
 {path:'login',loadComponent:()=>import('./features/login').then(m=>m.LoginComponent)},
 {path:'',canActivate:[authGuard],loadComponent:()=>import('./features/shell').then(m=>m.ShellComponent),children:[
  {path:'',pathMatch:'full',canActivate:[()=>inject(Router).parseUrl(homeFor(inject(SessionService).user()?.rol))],children:[]},
  {path:'comprador/catalogo',canActivate:[roleGuard('COMPRADOR')],loadComponent:()=>import('./features/products').then(m=>m.ProductsComponent)},
  {path:'comprador/pedidos',canActivate:[roleGuard('COMPRADOR')],loadComponent:()=>import('./features/orders').then(m=>m.OrdersComponent)},
  {path:'comprador/pedidos/:pedidoId',canActivate:[roleGuard('COMPRADOR')],loadComponent:()=>import('./features/order-detail').then(m=>m.OrderDetailComponent)},
  {path:'vendedor/productos',canActivate:[roleGuard('VENDEDOR')],loadComponent:()=>import('./features/products').then(m=>m.ProductsComponent)},
  {path:'vendedor/pedidos',canActivate:[roleGuard('VENDEDOR')],loadComponent:()=>import('./features/orders').then(m=>m.OrdersComponent)},
  {path:'vendedor/pedidos/:pedidoId',canActivate:[roleGuard('VENDEDOR')],loadComponent:()=>import('./features/order-detail').then(m=>m.OrderDetailComponent)},
  {path:'admin',canMatch:[adminCanMatch],loadComponent:()=>import('./features/admin').then(m=>m.AdminComponent)},
  {path:'**',redirectTo:''}
 ]}
];
