import { Component, inject, Injectable, InjectionToken, OnInit, signal } from '@angular/core';
import { Routes, Router, RouterOutlet } from '@angular/router';
import { loadRemoteModule } from '@angular-architects/module-federation';
import { CONFIG } from '../core/config';
import { UI } from '../shared/ui';
export interface AdminRemote { ADMIN_ROUTES:Routes; }
export const REMOTE_LOADER=new InjectionToken<(url:string)=>Promise<AdminRemote>>('Admin remote loader',{providedIn:'root',factory:()=>url=>loadRemoteModule<AdminRemote>({type:'module',remoteEntry:url,exposedModule:'./Routes'})});
@Injectable({providedIn:'root'})
export class AdminRemoteService {
 private load=inject(REMOTE_LOADER);private config=inject(CONFIG);private router=inject(Router);private installed=false;private attempts=0;
 async mount(){
  if(this.installed)return;
  const entry=new URL(this.config.adminRemoteEntry,document.baseURI);
  // Browsers cache failed ESM imports. A fresh URL makes an explicit retry real.
  if(this.attempts++>0)entry.searchParams.set('mfRetry',`${Date.now()}-${this.attempts}`);
  const remote=await this.load(entry.href);
  if(!Array.isArray(remote.ADMIN_ROUTES))throw Error('Remote contract');
  const config=this.router.config.map(route=>route.path===''?{...route,children:route.children?.map(child=>child.path==='admin'?{...child,children:remote.ADMIN_ROUTES}:child)}:route);
  this.router.resetConfig(config);this.installed=true;
 }
}
@Component({standalone:true,imports:[...UI,RouterOutlet],template:`
@if(loading()){<div class="empty" role="status"><lucide-icon name="loader-circle"/><h1>Abriendo administración</h1><p>Espera un momento.</p><mat-progress-bar mode="indeterminate"/></div>}
@if(failed()){<section class="empty" aria-live="polite"><span class="empty-icon"><lucide-icon name="unplug" size="32"/></span><p class="eyebrow">ADMINISTRACIÓN</p><h1>Módulo de administración no disponible</h1><p>No pudimos abrir este módulo. Puedes volver a intentarlo sin cerrar tu sesión.</p><button mat-flat-button color="primary" (click)="retry()"><lucide-icon name="refresh-cw" size="18"/> Reintentar</button></section>}
<router-outlet/>`})
export class AdminComponent implements OnInit {
 private remote=inject(AdminRemoteService);private router=inject(Router);loading=signal(false);failed=signal(false);
 ngOnInit(){void this.retry();}
 async retry(){if(this.loading())return;this.loading.set(true);this.failed.set(false);try{await this.remote.mount();await this.router.navigateByUrl(this.router.url,{onSameUrlNavigation:'reload'});}catch{this.failed.set(true);}finally{this.loading.set(false);}}
}
