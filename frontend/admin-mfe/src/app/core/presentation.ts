import { HttpErrorResponse } from '@angular/common/http';
import { inject, Injectable } from '@angular/core';
import { MatSnackBar } from '@angular/material/snack-bar';
import { Carga } from './models';
export function errorMessage(error:unknown):string {
 const status=error instanceof HttpErrorResponse?error.status:0;
 const messages:Record<number,string>={0:'No se pudo conectar. Revisa la conexión y vuelve a intentar.',400:'Revisa los datos de la solicitud o el archivo seleccionado.',401:'Tu sesión no está disponible. Ingresa desde el host.',403:'No tienes permiso para realizar esta acción.',404:'No se encontró el pedido, carga o reporte.',409:'La operación no está disponible en el estado actual o ya fue solicitada. Actualiza la información.',413:'El archivo supera el tamaño permitido.',500:'No se pudo completar la operación. Inténtalo más tarde.',503:'El servicio no está disponible temporalmente.'};
 return messages[status]??'No se pudo completar la operación.';
}
export function validateFile(file:File|null,max:number):string|null{
 if(!file)return 'Selecciona un archivo XLSX.';
 if(!/\.xlsx$/i.test(file.name))return 'Solo se admiten archivos .xlsx.';
 if(file.size===0)return 'El archivo está vacío.';
 if(file.size>max)return `El archivo supera el límite de ${(max/1024/1024).toFixed(0)} MiB.`;
 if(file.name.length>200||/[\\/\x00-\x1f\x7f]/.test(file.name))return 'El nombre del archivo no es válido.';
 return null;
}
export function progressOf(c:Carga):number|null{if(c.totales.filas<=0)return null;return Math.min(100,Math.round(100*(c.totales.aceptadas+c.totales.rechazadas+c.totales.duplicadas)/c.totales.filas));}
export function reportFilename(disposition:string|null,id:string):string{
 const fallback=`reporte-${id.replace(/[^A-Za-z0-9-]/g,'')}.xlsx`;
 if(!disposition)return fallback;
 let value=/filename\*=UTF-8''([^;]+)/i.exec(disposition)?.[1]??/filename="([^"]+)"/i.exec(disposition)?.[1]??/filename=([^;]+)/i.exec(disposition)?.[1];
 if(!value)return fallback;try{value=decodeURIComponent(value.trim());}catch{return fallback;}
 return /^[^\\/\x00-\x1f\x7f]{1,200}\.xlsx$/i.test(value)?value:fallback;
}
@Injectable({providedIn:'root'})
export class AdminFeedback {
 private snack=inject(MatSnackBar);
 show(message:string,error=false){this.snack.open(message,'Cerrar',{duration:6500,politeness:error?'assertive':'polite',panelClass:error?'admin-notice-error':'admin-notice-info'});}
}
@Injectable({providedIn:'root'})
export class FileDownloader {
 save(blob:Blob,name:string){const url=URL.createObjectURL(blob);const a=document.createElement('a');a.href=url;a.download=name;a.hidden=true;document.body.append(a);try{a.click();}finally{a.remove();setTimeout(()=>URL.revokeObjectURL(url),0);}}
}
