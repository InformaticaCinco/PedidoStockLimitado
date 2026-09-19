import { inject, Injectable, signal } from '@angular/core';
import { RECENT_STORAGE } from './config';
export const RECENT_KEY='admin-mfe.recentLoads';
@Injectable({providedIn:'root'})
export class RecentLoadsService {
 private storage=inject(RECENT_STORAGE);readonly ids=signal<string[]>(this.restore());
 private restore():string[]{try{const raw:unknown=JSON.parse(this.storage.getItem(RECENT_KEY)??'[]');return Array.isArray(raw)?[...new Set(raw.filter((id):id is string=>typeof id==='string'&&/^CG-[A-Za-z0-9-]{1,60}$/.test(id)))].slice(0,10):[];}catch{return [];}}
 add(id:string){if(!/^CG-[A-Za-z0-9-]{1,60}$/.test(id))return;this.save([id,...this.ids().filter(x=>x!==id)].slice(0,10));}
 remove(id:string){this.save(this.ids().filter(x=>x!==id));}
 clear(){this.save([]);}
 private save(ids:string[]){this.ids.set(ids);try{if(ids.length)this.storage.setItem(RECENT_KEY,JSON.stringify(ids));else this.storage.removeItem(RECENT_KEY);}catch{/* memory fallback when storage denied */}}
}
