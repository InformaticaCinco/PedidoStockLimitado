import { InjectionToken } from '@angular/core';
export interface AppConfig { javaApi: string; despachosApi: string; cargasApi: string; adminRemoteEntry: string; }
declare global { interface Window { __PEDIDOS_CONFIG__?: Partial<AppConfig>; } }
export const CONFIG = new InjectionToken<AppConfig>('AppConfig', { providedIn: 'root', factory: () => ({
  javaApi: '/api/java', despachosApi: '/api/despachos', cargasApi: '/api/cargas',
  adminRemoteEntry: 'http://localhost:8081/remoteEntry.js', ...window.__PEDIDOS_CONFIG__
}) });
export const SESSION_STORAGE = new InjectionToken<Storage>('Session storage', {providedIn: 'root', factory: () => sessionStorage});
