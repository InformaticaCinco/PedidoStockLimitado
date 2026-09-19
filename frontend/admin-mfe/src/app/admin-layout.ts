import { Component, inject, OnDestroy, ViewEncapsulation } from '@angular/core';
import { RouterLink, RouterLinkActive, RouterOutlet } from '@angular/router';
import { RecentLoadsService } from './core/recent-loads';
import { UI } from './shared/ui';
@Component({standalone:true,imports:[...UI,RouterLink,RouterLinkActive,RouterOutlet],encapsulation:ViewEncapsulation.None,styleUrls:['./admin-ui.scss'],template:`<section class="admin-mfe"><nav class="adm-subnav" aria-label="Secciones de administración"><a routerLink="dashboard" routerLinkActive="selected" #d="routerLinkActive" [attr.aria-current]="d.isActive?'page':null"><lucide-icon name="layout-dashboard" size="18"/>Dashboard</a><a routerLink="cargas" routerLinkActive="selected" #c="routerLinkActive" [attr.aria-current]="c.isActive?'page':null"><lucide-icon name="upload" size="18"/>Carga masiva</a><a routerLink="revision" routerLinkActive="selected" #r="routerLinkActive" [attr.aria-current]="r.isActive?'page':null"><lucide-icon name="list-checks" size="18"/>Revisión</a></nav><router-outlet/></section>`})
export class AdminLayout implements OnDestroy {
 private recent=inject(RecentLoadsService);
 // Leaving ADMIN (including logout) prevents another account inheriting recent IDs.
 // Navigating between its children preserves them; browser reload restores sessionStorage.
 ngOnDestroy(){this.recent.clear();}
}
