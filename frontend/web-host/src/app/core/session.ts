import { computed, inject, Injectable, OnDestroy, signal } from '@angular/core';
import { Router } from '@angular/router';
import { catchError, finalize, Observable, of, shareReplay, tap, throwError } from 'rxjs';
import { AuthApiService } from './api';
import { SESSION_STORAGE } from './config';
import { AuthResponse, Role, Session } from './models';
export const SESSION_KEY='pedidos.session.v1';
export const homeFor=(role?:Role)=>role==='ADMIN'?'/admin':role==='VENDEDOR'?'/vendedor/productos':'/comprador/catalogo';
@Injectable({providedIn:'root'})
export class SessionService implements OnDestroy {
  private api=inject(AuthApiService); private storage=inject(SESSION_STORAGE); private router=inject(Router);
  readonly session=signal<Session|null>(null); readonly user=computed(()=>this.session()?.usuario??null);
  private flight?:Observable<AuthResponse>; private timer?:ReturnType<typeof setTimeout>; private generation=0;
  constructor(){ this.restore(); }
  restore(){
    try {
      const raw=this.storage.getItem(SESSION_KEY); if(!raw)return;
      const s:Session=JSON.parse(raw);
      if(!s.accessToken || !s.refreshToken || !Number.isFinite(s.expiresAt) || !s.usuario?.id || !['ADMIN','VENDEDOR','COMPRADOR'].includes(s.usuario.rol)) throw Error('invalid session');
      this.session.set(s); this.schedule();
    } catch { this.clear(); }
  }
  login(usuario:string,clave:string){ const generation=++this.generation; return this.api.login(usuario,clave).pipe(tap(s=>{if(generation===this.generation)this.save(s);})); }
  private save(s:AuthResponse){const session={...s,expiresAt:Date.now()+s.expiraEn*1000};this.session.set(session);try{this.storage.setItem(SESSION_KEY,JSON.stringify(session));}catch{/* memory-only if browser denies storage */}this.schedule();}
  private schedule(){clearTimeout(this.timer);const s=this.session();if(s)this.timer=setTimeout(()=>this.refresh().subscribe({error:()=>undefined}),Math.max(0,s.expiresAt-Date.now()-30000));}
  refresh():Observable<AuthResponse>{
    if(this.flight)return this.flight;
    const s=this.session();if(!s)return throwError(()=>Error('Sesión ausente'));
    const generation=this.generation;
    const request=this.api.refresh(s.refreshToken).pipe(
      tap(value=>{if(generation!==this.generation){this.api.logout(value.refreshToken).subscribe({error:()=>undefined});throw Error('Sesión cerrada');}this.save(value);}),
      catchError(error=>{if(generation===this.generation)this.expire();return throwError(()=>error);}),
      finalize(()=>{if(this.flight===request)this.flight=undefined;}),
      shareReplay({bufferSize:1,refCount:false})
    );this.flight=request;return request;
  }
  logout(){
    // Wait for an in-flight rotation before revoking its successor.
    const token=this.session()?.refreshToken;
    const pending=this.flight;
    this.clear();void this.router.navigateByUrl('/login');
    if(pending){pending.subscribe({next:s=>this.api.logout(s.refreshToken).subscribe({error:()=>undefined}),error:()=>{if(token)this.api.logout(token).subscribe({error:()=>undefined});}});}
    else if(token)this.api.logout(token).subscribe({error:()=>undefined});
  }
  clear(){this.generation++;clearTimeout(this.timer);this.session.set(null);try{this.storage.removeItem(SESSION_KEY);}catch{/* storage unavailable */}}
  expire(){this.clear();void this.router.navigateByUrl('/login');}
  ngOnDestroy(){clearTimeout(this.timer);}
}
