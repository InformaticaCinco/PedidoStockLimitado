import { HttpErrorResponse } from '@angular/common/http';
import { inject, Injectable } from '@angular/core';
import { MatSnackBar } from '@angular/material/snack-bar';
export function errorMessage(error:unknown):string {
  const code=error instanceof HttpErrorResponse?error.status:0;
  const messages:Record<number,string>={0:'No se pudo conectar. Comprueba tu conexión y reintenta.',400:'Revisa los datos ingresados y vuelve a intentar.',401:'La sesión o las credenciales no son válidas. Inicia sesión nuevamente.',403:'No tienes permiso para realizar esta acción.',404:'No se encontró el recurso solicitado.',409:'La operación entra en conflicto con el estado actual. Actualiza y revisa los datos.',422:'Hay datos que no pudieron validarse. Revisa el formulario.',500:'Ocurrió un error en el servicio. Inténtalo más tarde.',503:'El servicio no está disponible temporalmente. Inténtalo de nuevo.'};
  return messages[code]??'No se pudo completar la operación. Inténtalo de nuevo.';
}
@Injectable({providedIn:'root'})
export class Notifications {
  private snack=inject(MatSnackBar);
  show(message:string,kind:'info'|'success'|'warning'|'error'='info'){this.snack.open(message,'Cerrar',{duration:6000,politeness:kind==='error'?'assertive':'polite',panelClass:[`notice-${kind}`]});}
}
