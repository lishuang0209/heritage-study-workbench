type ShotText = {content:string;camera:string;scene:string};

const clauses = (text:string) => text.split(/[，,。；;\n]+|(?<!\d)[:：]/).map(value=>value.trim()).filter(Boolean);
const restriction = /(?:不(?:另|再|凭|得|能|要|应|使用|新增|增加|补造|添加|画|出现|展示|改变|切镜|拆解|猜测|推测|复原|放大)|禁止|避免|无人物|无人出镜|未提供|只观察|不占满)/;
const style = /水墨|工笔|淡彩|泼墨|写意|细线|薄染|笔触|晕染|低饱和|设色|宣纸|墨色|绢本/;
const composition = /景别|远景|全景|中景|近景|特写|机位|取景|平视|仰视|俯视|仰拍|俯拍|构图|侧前方|斜侧|画面[中左右前后]|前景|远侧|背景|中后部|居于|视角|角度|留白/;
const sentence = (parts:string[]) => parts.length ? parts.join('，')+'。' : '';
const normalized = (text:string) => text.replace(/不(?:另造|补造)/g,'不生成');

// Presentation only: never rewrite the saved prompt or remove its generation data.
export function shotDescription(shot:ShotText):string {
  const [brief,...supplement] = shot.content.split('\n画面补充：');
  const main = supplement.length ? supplement.join('\n') : brief;
  const subjects:string[]=[], framing:string[]=[], styles:string[]=[], limits:string[]=[];
  const add = (list:string[],text:string) => {
    const value=text.replace(/^已确认的?/, '').replace(/取景$/, '').trim();
    if(value&&!list.some(item=>normalized(item)===normalized(value)))list.push(value);
  };
  clauses(shot.camera).forEach(part=>add(framing,part));
  for(const part of clauses(main)) {
    if(restriction.test(part))add(limits,part);
    else if(composition.test(part)&&!style.test(part))add(framing,part);
    else if(style.test(part)&&!/前景|远侧|背景|居于/.test(part))add(styles,part.replace(/(?:过肩近景|大特写|中近景|远景|全景|中景|近景|特写)$/,''));
    else add(subjects,part);
  }
  // The old planner prepended instructions to its visual description. Keep
  // explicit restrictions visible without repeating that boilerplate as a scene.
  if(supplement.length)clauses(brief).filter(part=>restriction.test(part)).forEach(part=>add(limits,part));
  return [sentence(subjects)||shot.scene||'当前场景',sentence(framing),sentence(styles),sentence(limits)]
    .filter(Boolean).map(part=>/[。！？]$/.test(part)?part:part+'。').join('');
}
