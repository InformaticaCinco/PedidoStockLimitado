import { Component } from '@angular/core';
import { bootstrapApplication } from '@angular/platform-browser';
import { provideAnimations } from '@angular/platform-browser/animations';
import { provideHttpClient } from '@angular/common/http';
import { provideRouter, RouterOutlet } from '@angular/router';
import { ADMIN_ROUTES } from './app/admin.routes';
@Component({selector:'admin-root',standalone:true,imports:[RouterOutlet],template:`<main class="standalone"><p class="dev-notice">Ejecutar dentro de web-host para sesión real. Esta vista de desarrollo no incluye login.</p><router-outlet/></main>`,styles:[`.standalone{max-width:1280px;margin:auto;padding:24px}.dev-notice{padding:12px;background:#fff5e8;color:#754400;border-radius:6px}`]})
class StandaloneApp {}
// Only standalone development provides an unauthenticated client. Never exported.
bootstrapApplication(StandaloneApp,{providers:[provideAnimations(),provideHttpClient(),provideRouter(ADMIN_ROUTES)]}).catch(()=>{document.body.textContent='No se pudo iniciar el módulo. Recarga la página.';});
