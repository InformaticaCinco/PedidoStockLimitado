import { Component, inject, signal } from '@angular/core';
import { AbstractControl, FormBuilder, ReactiveFormsModule, Validators } from '@angular/forms';
import { Router, RouterLink } from '@angular/router';
import { finalize } from 'rxjs';
import { SessionService, homeFor } from '../core/session';
import { errorMessage } from '../core/errors';
import { UI } from '../shared/ui';
@Component({standalone:true,imports:[...UI,ReactiveFormsModule,RouterLink],template:`
<main class="login-layout"><section class="login-brand"><a class="brand" routerLink="/login"><span class="brand-icon"><lucide-icon name="package-check"/></span>Gestión de Pedidos</a><div class="brand-story"><p class="eyebrow">DE PRINCIPIO A ENTREGA</p><h1>Tus pedidos.<br>Todo en su lugar.</h1><p>Consulta productos, gestiona tus pedidos y sigue cada paso de su despacho desde un solo lugar.</p><div class="story-steps"><span><lucide-icon name="shopping-bag"/> Elige</span><span><lucide-icon name="package"/> Gestiona</span><span><lucide-icon name="truck"/> Sigue</span></div></div><p class="brand-footer">Simple. Claro. Conectado.</p></section>
<section class="login-panel"><form [formGroup]="form" (ngSubmit)="submit()" class="login-form"><p class="eyebrow">BIENVENIDO</p><h2>Inicia sesión</h2><p class="muted">Ingresa con tu cuenta para continuar.</p>
<mat-form-field appearance="outline"><mat-label>Usuario</mat-label><input matInput formControlName="usuario" autocomplete="username" maxlength="100"/><mat-error>Ingresa tu usuario (máximo 100 caracteres).</mat-error></mat-form-field>
<mat-form-field appearance="outline"><mat-label>Contraseña</mat-label><input matInput formControlName="clave" [type]="hidden()?'password':'text'" autocomplete="current-password"/><button mat-icon-button matSuffix type="button" (click)="hidden.set(!hidden())" [attr.aria-label]="hidden()?'Mostrar contraseña':'Ocultar contraseña'"><lucide-icon [name]="hidden()?'eye':'eye-off'" size="20"/></button><mat-error>Ingresa una contraseña de hasta 72 bytes.</mat-error></mat-form-field>
@if(error()){<p class="feedback error" role="alert">{{error()}}</p>}
<button mat-flat-button color="primary" class="full" [disabled]="form.invalid || busy()">{{busy()?'Iniciando sesión…':'Ingresar'}}<lucide-icon name="arrow-right" size="18"/></button>
@if(busy()){<mat-progress-bar mode="indeterminate" aria-label="Iniciando sesión"/>}
<p class="login-note"><lucide-icon name="shield-check" size="16"/>Tu espacio de trabajo, según tu perfil.</p></form></section></main>`,styles:[`
.login-layout{min-height:100dvh;display:grid;grid-template-columns:1fr 1fr}.login-brand{background:var(--color-surface-soft);padding:48px 12%;display:flex;flex-direction:column;border-right:1px solid var(--color-border)}.brand-story{margin:auto 0;padding:80px 0}.brand-story h1{font-size:clamp(32px,4vw,52px);line-height:1.15;letter-spacing:-1.5px;font-weight:650}.brand-story>p:not(.eyebrow){max-width:390px;color:var(--color-text-secondary);line-height:1.8}.story-steps{display:flex;flex-wrap:wrap;gap:24px;margin-top:40px}.story-steps span{display:flex;align-items:center;gap:8px;font-size:13px;color:var(--color-primary)}.brand-footer{font-size:12px;color:var(--color-text-secondary)}.login-panel{display:grid;place-items:center;padding:40px}.login-form{width:100%;max-width:380px}.login-form h2{font-size:30px;letter-spacing:-.7px;margin:12px 0}.login-form>.muted{margin-bottom:32px}.login-form mat-form-field{width:100%;margin-bottom:8px}.login-note{display:flex;gap:8px;align-items:center;justify-content:center;margin-top:28px;font-size:12px;color:var(--color-text-secondary)}@media(max-width:760px){.login-layout{grid-template-columns:1fr}.login-brand{padding:24px;border-right:0;border-bottom:1px solid var(--color-border)}.brand-story,.brand-footer{display:none}.login-panel{padding:40px 24px;align-items:start}.login-form h2{font-size:26px}}
`]})
export class LoginComponent {
 private auth=inject(SessionService);private router=inject(Router);private fb=inject(FormBuilder);
 hidden=signal(true);busy=signal(false);error=signal('');
 form=this.fb.nonNullable.group({usuario:['',[Validators.required,Validators.maxLength(100)]],clave:['',[Validators.required,(c:AbstractControl)=>new TextEncoder().encode(c.value as string).length>72?{bytes:true}:null]]});
 submit(){if(this.form.invalid||this.busy())return;this.busy.set(true);this.error.set('');const {usuario,clave}=this.form.getRawValue();this.auth.login(usuario,clave).pipe(finalize(()=>this.busy.set(false))).subscribe({next:s=>{this.form.controls.clave.reset();void this.router.navigateByUrl(homeFor(s.usuario.rol));},error:e=>this.error.set(errorMessage(e))});}
}
