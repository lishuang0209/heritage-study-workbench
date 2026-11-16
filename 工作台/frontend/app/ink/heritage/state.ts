export type Mark = {kind:'rectangle'|'arrow';x:number;y:number;x2:number;y2:number};
export type Photo = {image:string;source:string;author:string;license:string;mark:Mark|null;mode:'contain'|'cover';focus_x:number;focus_y:number;url?:string;preview_url?:string};
export type Station = {building:string;name:string;component:string;grade:string;standing_position:string;checked_description:string;objective:string;instruction:string;question:string;panorama:Photo|null;detail:Photo|null};
export type StudyScript = {intro:string;location:string;task:string;version:number;station_version:number;confirmed_version:number|null};
export type HeritageFields = {project_type?:'ink'|'heritage';heritage_station?:Station;heritage_version?:number;heritage_confirmed_version?:number|null;heritage_ready?:boolean;heritage_script?:StudyScript;task_card_url?:string|null;task_card_stale?:boolean;heritage_chapters?:{kind:string;duration:number;video:string}[];heritage_trial?:{participants:number;found_without_hint:number;preparation_minutes:number;notes:string}};
export const blankStation = ():Station => ({building:'',name:'',component:'',grade:'',standing_position:'',checked_description:'',objective:'',instruction:'',question:'',panorama:null,detail:null});
export function stationPayload(station:Station) {
  const clean = (photo:Photo|null) => photo ? Object.fromEntries(Object.entries(photo).filter(([key])=>!['url','preview_url'].includes(key))) : null;
  return {...station,panorama:clean(station.panorama),detail:clean(station.detail)};
}
export function point(x:number,y:number,bounds:{left:number;top:number;width:number;height:number}) {
  return {x:Math.max(0,Math.min(1,(x-bounds.left)/bounds.width)),y:Math.max(0,Math.min(1,(y-bounds.top)/bounds.height))};
}
