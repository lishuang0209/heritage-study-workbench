import type {Shot} from '../ink-shared';

export function visitRoute(shots:Pick<Shot,'study_visit'>[]):string {
 const stops:string[]=[];
 for(const shot of shots){const label=shot.study_visit?.label;if(label&&label!==stops.at(-1))stops.push(label);}
 return stops.join(' → ');
}
export function visitTitle(shot:Pick<Shot,'study_visit'|'study_topic'|'scene'>):string {
 return [shot.study_visit?.label,shot.study_topic||shot.scene].filter(Boolean).join(' · ');
}
