export type Mark = {kind:'rectangle'|'arrow';x:number;y:number;x2:number;y2:number};
export type Photo = {credit_kind?:'manual'|'unresolved'|'catalog'|'self'|'authorized';derived_from?:string|null;derived_mark?:Mark|null;image:string;source:string;author:string;license:string;mark:Mark|null;mode:'contain'|'cover';focus_x:number;focus_y:number;url?:string;preview_url?:string};
export type Station = {building:string;name:string;component:string;grade:string;standing_position:string;checked_description:string;objective:string;instruction:string;question:string;panorama:Photo|null;detail:Photo|null};
export type Timing = {intro:number;location:number;task:number};
export type StudyScript = {timing_version?:number;intro:string;location:string;task:string;version:number;station_version:number;confirmed_version:number|null};
export type SettingResearchReference = {group:'scenes'|'props';asset_id:string;asset_name:string;mode:'research';layout:'panoramic-single-view'|'component-single-view';error:string};
export type HeritageFields = {heritage_guide?:{enabled:boolean;character_id:string;name:string;desc:string;fictional:boolean;era:string;source?:string};heritage_guide_version?:number;heritage_narration?:{voice:string;label:string;speed:number;choices:{voice:string;label:string;speed:number}[]};heritage_story_stale?:boolean;heritage_setting_references?:SettingResearchReference[];heritage_timing?:Timing;heritage_timing_version?:number;project_type?:'ink'|'heritage';heritage_station?:Station;heritage_version?:number;heritage_confirmed_version?:number|null;heritage_confirmed_snapshot?:Station;heritage_ready?:boolean;heritage_script?:StudyScript;task_card_url?:string|null;task_card_stale?:boolean;heritage_chapters?:{kind:string;duration:number;video:string}[];heritage_trial?:{participants:number;found_without_hint:number;preparation_minutes:number;notes:string}};
export const blankStation = ():Station => ({building:'',name:'',component:'',grade:'',standing_position:'',checked_description:'',objective:'',instruction:'',question:'',panorama:null,detail:null});
// Read legacy two-field projects without mutating their saved revision.
export function observationGuidance(station:Pick<Station,'standing_position'|'instruction'>):string {
  const position=station.standing_position.trim();
  const instruction=station.instruction.trim();
  if (!position || instruction.includes(position)) return instruction;
  if (!instruction || position.includes(instruction)) return position;
  return position+(/[。！？!?；;]$/.test(position)?'':'。')+instruction;
}
export function stationPayload(station:Station) {
  const clean = (photo:Photo|null) => photo ? Object.fromEntries(Object.entries(photo).filter(([key])=>!['url','preview_url'].includes(key))) : null;
  return {...station,instruction:observationGuidance(station),standing_position:'',panorama:clean(station.panorama),detail:clean(station.detail)};
}
export function point(x:number,y:number,bounds:{left:number;top:number;width:number;height:number}) {
  return {x:Math.max(0,Math.min(1,(x-bounds.left)/bounds.width)),y:Math.max(0,Math.min(1,(y-bounds.top)/bounds.height))};
}

// Draft only generic observation tasks; never invent facts or a safe standing position.
export function completeStationDraft(station:Station):Station {
  const component=station.component.trim();
  if (!component) return {...station};
  const defaults={
    name:`找${component}`.slice(0,80),
    objective:`对照实拍照片找到${component}，观察它的外形特点。`.slice(0,300),
    instruction:`在老师指定的安全位置，对照照片标注，指出同一处${component}。`.slice(0,220),
    question:`你从哪些外形特点认出了${component}？`.slice(0,160),
  };
  const next={...station};
  for (const key of ['name','objective','instruction','question'] as const) {
    if (!next[key].trim()) next[key]=defaults[key];
  }
  return next;
}

export function selectPhotoCredits(photo:Photo,kind:'self'|'authorized'):Photo {
  return {...photo,credit_kind:kind,...(kind==='self'?{
    source:'上传者本人拍摄',author:'上传者本人',license:'上传者确认可用于本次研学短片与任务卡',
  }:{
    source:'上传者提供的授权照片',author:'照片提供方（上传者确认授权）',license:'上传者声明已获本次研学短片与任务卡的使用授权',
  })};
}

// A deliberate review click saves first and confirms the returned revision once.
export async function reviewStation<T extends HeritageFields>(current:T,dirty:boolean,save:()=>Promise<T>,confirm:(saved:T)=>Promise<T>):Promise<T> {
  const saved=dirty?await save():current;
  return saved.heritage_ready?saved:confirm(saved);
}

export function scriptIsConfirmed(project:HeritageFields):boolean {
  const script=project.heritage_script;
  return Boolean(script && script.confirmed_version===script.version &&
    script.station_version===(project.heritage_version||0) &&
    (script.timing_version||0)===(project.heritage_timing_version||0));
}

// Advance only after the server confirms the current script, station and timing.
export async function reviewScript<T extends HeritageFields>(current:T,confirm:(saved:T)=>Promise<T>):Promise<T> {
  if (!current.heritage_script) throw new Error('请先生成或保存研学脚本');
  if (scriptIsConfirmed(current)) return current;
  const reviewed=await confirm(current);
  if (!scriptIsConfirmed(reviewed)) throw new Error('脚本尚未确认成功，请核对后重试');
  return reviewed;
}

export function derivedDetailStale(station:Station):boolean {
  const detail=station.detail;
  if(!detail?.derived_from)return false;
  const source=station.panorama;
  if(detail.derived_from!==source?.image||!source?.mark||!detail.derived_mark)return true;
  return (['kind','x','y','x2','y2'] as const).some(key=>source.mark![key]!==detail.derived_mark![key]);
}

const defaultTiming:Timing={intro:12,location:11,task:7};
export function projectTiming(project:HeritageFields):Timing {return {...(project.heritage_timing||defaultTiming)};}
export function timingError(timing:Timing):string {
  if(Object.values(timing).some(n=>!Number.isInteger(n)||n<3||n>180))return '每段时长请填写3–180秒的整数';
  return Object.values(timing).reduce((a,b)=>a+b,0)>300?'总时长不能超过300秒':'';
}
export function observationSplit(seconds:number,detail:boolean):{panorama:number;detail:number} {
  const panorama=detail?Math.ceil(seconds*6/11):seconds;
  return {panorama,detail:seconds-panorama};
}

export function mergeHistoryMaterial(material:string,history:string,sources:{title:string;url:string}[]=[]):string {
  const facts=history.split(/[。！？]/).map(fact=>fact.trim()).filter(Boolean);
  const missing=facts.filter(fact=>!material.includes(fact));
  const links=sources.filter(source=>!material.includes(source.url));
  return [material.trim(), ...missing.map(fact=>'历史背景：'+fact+'。'), ...links.map(source=>'资料来源：'+source.title+' '+source.url)].filter(Boolean).join('\n');
}

export function narrationEstimate(text:string):{characters:number;minimum:number;maximum:number} {
  const characters=text.replace(/\s/g,'').length;
  return {characters,minimum:Math.ceil(characters/4),maximum:Math.ceil(characters/3)};
}
