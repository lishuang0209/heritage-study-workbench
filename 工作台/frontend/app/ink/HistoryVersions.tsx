import type { ReactNode } from 'react';

export type HistoryMeta = { deleted_at?:number|null; can_delete?:boolean; delete_block_reason?:string };

type HistoryStatus = 'using'|'pending'|'reference'|'history'|'discarded'|'deleted';

export function HistoryBadge({children,state='history'}:{children:ReactNode;state?:HistoryStatus}) {
  return <span className="ink-history-badge" data-state={state}><span className="ink-history-status-dot" aria-hidden="true"/>{children}</span>;
}

export function HistoryVersions<T extends HistoryMeta>({items,itemKey,renderItem}:{items:T[];itemKey:(item:T)=>string;renderItem:(item:T)=>ReactNode}) {
  const available=items.filter(item=>!item.deleted_at);
  const removed=items.filter(item=>item.deleted_at);
  const cards=(versions:T[])=><div className="ink-history-grid">{versions.map(item=><article key={itemKey(item)}>{renderItem(item)}</article>)}</div>;
  return <>
    {available.length?cards(available):<p>暂无可用的历史版本。</p>}
    {removed.length?<details className="ink-history-removed"><summary>已删除版本（{removed.length}）</summary><p>恢复后重新出现在历史列表，不会替换当前使用的版本。</p>{cards(removed)}</details>:null}
  </>;
}
