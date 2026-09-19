import { Component } from '@angular/core';
import { MatDialogModule } from '@angular/material/dialog';
import { MatButtonModule } from '@angular/material/button';
@Component({standalone:true,imports:[MatDialogModule,MatButtonModule],template:`<h2 mat-dialog-title>¿Solicitar anulación?</h2><mat-dialog-content>Se solicitará detener el pedido y revertir las operaciones que correspondan. El proceso puede tardar unos momentos.</mat-dialog-content><mat-dialog-actions align="end"><button mat-button [mat-dialog-close]="false">Volver</button><button mat-flat-button color="warn" [mat-dialog-close]="true">Solicitar anulación</button></mat-dialog-actions>`})
export class CancelDialog {}
