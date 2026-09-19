import { importProvidersFrom } from '@angular/core';
import { Routes } from '@angular/router';
import { MatDialogModule } from '@angular/material/dialog';
import { MatSnackBarModule } from '@angular/material/snack-bar';
import { LucideAngularModule, LayoutDashboard, Upload, FileSpreadsheet, Download, RefreshCw, Search, CircleCheck, PackageSearch, ListChecks, Files } from 'lucide-angular';
import { AdminLayout } from './admin-layout';
// Deliberately no HttpClient/auth providers: inherit the host's client and interceptor.
export const ADMIN_ROUTES:Routes=[
 {path:'',pathMatch:'full',redirectTo:'dashboard'},
 {path:'',component:AdminLayout,providers:[importProvidersFrom(MatDialogModule,MatSnackBarModule,LucideAngularModule.pick({LayoutDashboard,Upload,FileSpreadsheet,Download,RefreshCw,Search,CircleCheck,PackageSearch,ListChecks,Files}))],children:[
  {path:'dashboard',loadComponent:()=>import('./features/orders').then(m=>m.OrdersComponent)},
  {path:'cargas',loadComponent:()=>import('./features/loads').then(m=>m.LoadsComponent)},
  {path:'revision',data:{review:true},loadComponent:()=>import('./features/orders').then(m=>m.OrdersComponent)}
 ]}
];
