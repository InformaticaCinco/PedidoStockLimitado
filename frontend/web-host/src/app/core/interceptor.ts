import { inject } from '@angular/core';
import { HttpErrorResponse, HttpInterceptorFn } from '@angular/common/http';
import { catchError, switchMap, throwError } from 'rxjs';
import { CONFIG } from './config';
import { SessionService } from './session';
export const sessionInterceptor:HttpInterceptorFn=(request,next)=>{
  const config=inject(CONFIG);
  const localApi=[config.javaApi,config.despachosApi,config.cargasApi].some(base=>request.url.startsWith(base+'/'));
  if(!localApi)return next(request);
  const auth=inject(SessionService);
  const correlated=request.clone({setHeaders:{'X-Correlation-Id':request.headers.get('X-Correlation-Id')||crypto.randomUUID()}});
  if(/\/auth\/(login|refresh|logout)$/.test(request.url))return next(correlated);
  const send=(token?:string)=>next(token?correlated.clone({setHeaders:{Authorization:`Bearer ${token}`}}):correlated);
  const recover=(error:unknown)=>{
    if(!(error instanceof HttpErrorResponse)||error.status!==401)return throwError(()=>error);
    auth.expire();return throwError(()=>error);
  };
  const current=auth.session();
  if(current && current.expiresAt-Date.now()<30000)return auth.refresh().pipe(switchMap(s=>send(s.accessToken)),catchError(recover));
  return send(current?.accessToken).pipe(catchError((error:unknown)=>{
    if(!(error instanceof HttpErrorResponse)||error.status!==401||!auth.session())return throwError(()=>error);
    // A late 401 from an older token must reuse the already-rotated token.
    const newer=auth.session();
    if(newer && newer.accessToken!==current?.accessToken)return send(newer.accessToken).pipe(catchError(recover));
    return auth.refresh().pipe(switchMap(s=>send(s.accessToken)),catchError(recover));
  }));
};
