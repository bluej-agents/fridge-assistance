const $ = id => document.getElementById(id);
const esc = value => String(value).replace(/[&<>"']/g, ch => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[ch]));
let lastRequest = null, lastResult = null, busy = false;
let modeChosen = false;
document.querySelectorAll('input[name=mode]').forEach(input=>input.addEventListener('change',()=>{modeChosen=true;}));
const ingredients = () => [...new Set($('ingredients').value.split(/[,，、\n;；]+/).map(s=>s.trim()).filter(Boolean).map(s=>({'西红柿':'番茄','包菜':'卷心菜','蒜':'大蒜'}[s]||s)))];
function readForm() {return {ingredients:ingredients(), people:Number($('people').value), minutes:Number($('minutes').value), vegetarian:$('vegetarian').checked, mode:document.querySelector('input[name=mode]:checked').value, exclude_ids:[],exclude_names:[]};}
function resetResult(){ $('results').hidden=true; $('empty').hidden=false; $('error').hidden=true; lastResult=null;setWorkspace('fridge'); }
function reveal(id){
 const target=$(id);
 target.focus({preventScroll:true});
 const rect=target.getBoundingClientRect?.();
 if(!rect||typeof window==='undefined'||rect.top<12||rect.bottom>window.innerHeight-12)target.scrollIntoView({block:'nearest',behavior:'instant'});
}
function setWorkspace(view){
 if(!['fridge','menu'].includes(view))return;
 $('workbench').dataset.view=view;
 $('show-fridge').setAttribute('aria-pressed',String(view==='fridge'));
 $('show-dinner').setAttribute('aria-pressed',String(view==='menu'));
}
$('show-fridge').addEventListener('click',()=>{setWorkspace('fridge');reveal('input-heading');});
$('show-dinner').addEventListener('click',()=>{setWorkspace('menu');reveal(lastResult?'result-heading':'empty');});
$('input-heading').setAttribute('tabindex','-1');$('empty').setAttribute('tabindex','-1');
$('choose-foods').addEventListener('click',()=>{if(!busy)$('ingredient-dialog').showModal();});
$('clear-ingredients').addEventListener('click',clearIngredients);
document.querySelectorAll('[data-close-dialog]').forEach(b=>b.addEventListener('click',()=>$(b.dataset.closeDialog).close()));
function selectFoodTab(key){
 if(!['meat','vegetables','eggs','seafood','grains'].includes(key))return;
 document.querySelectorAll('[data-food-tab]').forEach(b=>{const active=b.dataset.foodTab===key;b.setAttribute('aria-selected',String(active));b.setAttribute('tabindex',active?'0':'-1');$(b.getAttribute('aria-controls')).hidden=!active;});
}
function bindTabKeys(selector,property,keys,select){
 document.querySelectorAll(selector).forEach(b=>b.addEventListener('keydown',event=>{
  const index=keys.indexOf(b.dataset[property]);let next;
  if(event.key==='ArrowRight')next=(index+1)%keys.length;
  else if(event.key==='ArrowLeft')next=(index+keys.length-1)%keys.length;
  else if(event.key==='Home')next=0;
  else if(event.key==='End')next=keys.length-1;
  else return;
  event.preventDefault();select(keys[next]);document.querySelector(`${selector}[${property==='foodTab'?'data-food-tab':'data-result-tab'}="${keys[next]}"]`).focus();
 }));
}
document.querySelectorAll('[data-food-tab]').forEach(b=>b.addEventListener('click',()=>selectFoodTab(b.dataset.foodTab)));
bindTabKeys('[data-food-tab]','foodTab',['meat','vegetables','eggs','seafood','grains'],selectFoodTab);
setWorkspace('fridge');
$('example').addEventListener('click',()=>{if(busy)return;modeChosen=true;$('ingredients').value='鸡蛋、番茄、白菜';$('people').value='2';$('minutes').value='30';$('vegetarian').checked=true;document.querySelector('input[value=demo]').checked=true;setPickerStatus('');resetResult();syncPicker();reveal('selected-ingredients');});
$('meal-form').addEventListener('change',resetResult);
function syncPicker(){
 const foods=ingredients();
 $('selected-ingredients').innerHTML=foods.length?foods.map(food=>`<button class="selected-food" type="button" data-remove-food="${esc(food)}" aria-label="移除${esc(food)}">${esc(food)} <span aria-hidden="true">×</span></button>`).join(''):'<span class="tiny">还没选食材，点「选择 / 编辑食材」选一选。</span>';
 $('clear-ingredients').disabled=busy||!foods.length;
 document.querySelectorAll('[data-remove-food]').forEach(b=>b.addEventListener('click',()=>setPickedFood(b.dataset.removeFood,false)));
 document.querySelectorAll('[data-ingredient]').forEach(input=>{input.checked=foods.includes(input.dataset.ingredient);});
 document.querySelectorAll('.ingredient-category').forEach(group=>{
  const choices=[...group.querySelectorAll('[data-ingredient]')];
  const count=choices.filter(input=>input.checked).length;
  group.querySelector('.category-count').textContent=count?`已选 ${count}`:'';
  const button=group.querySelector('[data-select-category]');
  const action=choices.length&&count===choices.length?'取消全选':'全选';
  button.textContent=action;button.setAttribute('aria-label',action+button.dataset.categoryName);
 });
 $('picker-total').textContent=`已选 ${foods.length} 种食材，可随时修改。`;
 $('diet-hint').textContent=$('vegetarian').checked&&foods.some(food=>/肉|鸡胸|鸡腿|鸡翅|排骨|五花|鱼|虾|蟹|蛤|贝|鱿|肠|培根|火腿/.test(food))?'已选肉类或水产，但这顿选择了不吃肉，安排时不会使用它们。':'';
}
function setPickerStatus(message){$('picker-status').textContent=message;$('picker-feedback').textContent=message;}
function clearIngredients(){
 if(busy||!ingredients().length)return;
 $('ingredients').value='';lastRequest=null;setPickerStatus('');syncPicker();resetResult();reveal('choose-foods');
}
function toggleFoodCategory(key){
 if(busy||!['meat','vegetables','eggs','seafood','grains'].includes(key))return;
 const categoryFoods=[...$('food-'+key).querySelectorAll('[data-ingredient]')].map(input=>input.dataset.ingredient);
 const foods=ingredients();
 const allSelected=categoryFoods.every(food=>foods.includes(food));
 const next=allSelected?foods.filter(food=>!categoryFoods.includes(food)):[...new Set([...foods,...categoryFoods])];
 if(!allSelected&&next.length>40){setPickerStatus('一次最多选择 40 种食材，请先取消一些食材，再全选本类。');return;}
 $('ingredients').value=next.join('、');setPickerStatus('');syncPicker();resetResult();
}
document.querySelectorAll('[data-select-category]').forEach(button=>button.addEventListener('click',()=>toggleFoodCategory(button.dataset.selectCategory)));
function setPickedFood(food,selected){
 if(busy)return;
 const foods=ingredients();
 if(selected&&!foods.includes(food)&&foods.length>=40){setPickerStatus('一次最多选择 40 种食材。');syncPicker();return;}
 $('ingredients').value=(selected?[...new Set([...foods,food])]:foods.filter(f=>f!==food)).join('、');
 setPickerStatus('');syncPicker();resetResult();
}
document.querySelectorAll('[data-ingredient]').forEach(input=>input.addEventListener('change',()=>setPickedFood(input.dataset.ingredient,input.checked)));
$('ingredients').addEventListener('input',()=>{setPickerStatus('');syncPicker();resetResult();});
$('vegetarian').addEventListener('change',syncPicker);
syncPicker();
$('meal-form').addEventListener('submit',event=>{event.preventDefault();run(readForm());});
function recipeSnapshot(dish,people){
 return {id:dish.id,name:dish.name,minutes:dish.minutes,vegetarian:dish.vegetarian,
  ingredients:dish.ingredients.map(({name,amount,unit})=>({name,amount,unit})),
  staples:[...(dish.staples||[])],steps:[...dish.steps],servings:people};
}
function retainedPairMatches(request,plan){
 if(!Array.isArray(plan?.dishes)||plan.dishes.length!==2)return false;
 try{
  if(!plan.dishes.every(dish=>typeof dish.id==='string'&&dish.id.trim())||new Set(plan.dishes.map(dish=>dish.id)).size!==2)return false;
  const replacement=plan.dishes[1-request.keep_index];
  if((request.exclude_ids||[]).includes(replacement.id)||(request.exclude_names||[]).includes(replacement.name))return false;
  return JSON.stringify(recipeSnapshot(plan.dishes[request.keep_index],plan.people))===JSON.stringify(request.keep_recipe);
 }catch{return false;}
}
function replacementRequest(id){
 if(busy||!lastRequest||!lastResult||lastResult.plan.dishes.length!==2)return null;
 const replaceIndex=lastResult.plan.dishes.findIndex(d=>d.id===id);
 if(replaceIndex<0)return null;
 const keepIndex=1-replaceIndex,kept=lastResult.plan.dishes[keepIndex],replaced=lastResult.plan.dishes[replaceIndex];
 const recent=values=>[...new Set(values)].slice(-20);
 return {...lastRequest,
  exclude_ids:recent([...(lastRequest.exclude_ids||[]),replaced.id]),
  exclude_names:recent([...(lastRequest.exclude_names||[]),replaced.name]),
  keep_index:keepIndex,
  keep_recipe:recipeSnapshot(kept,lastResult.plan.people),
 };
}
function swapDish(id){const request=replacementRequest(id);if(request)return run(request);}
async function run(request){
 if(busy)return;
 if(!request.ingredients.length){setWorkspace('menu');$('error').textContent='先告诉我至少一种食材。';$('error').hidden=false;reveal('error');return;}
 setWorkspace('menu');
 busy=true;$('error').hidden=true;$('submit').disabled=true;
 document.querySelectorAll('form input, form select, form textarea, #ingredient-dialog input, #ingredient-dialog textarea, [data-select-category], .selected-food, #example, #choose-foods, #clear-ingredients, .swap').forEach(el=>el.disabled=true);
 $('status-message').className='loading';$('status-message').textContent=request.keep_recipe?'正在保留另一道菜，为你换一道家常菜……':request.mode==='agent'?'正在用你选的食材搭配两道家常菜，请稍等一会儿……':'正在从示例菜谱中搭配两道家常菜，请稍等……';
 $('meal-form').setAttribute('aria-busy','true');
 reveal('status-message');
 const controller=new AbortController();
 const timeout=setTimeout(()=>controller.abort(),100000);
 let destination='error';
 try{
   const response=await fetch('/api/plan',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(request),signal:controller.signal});
   const data=await response.json();
   if(!response.ok){
    const detail=data.detail;
    const message=typeof detail==='string'?detail:detail&&typeof detail.message==='string'?detail.message:'输入格式不合适，请使用简短食材名称并检查人数与时间。';
    const code=detail&&typeof detail.code==='string'&&/^[a-z_]{1,40}$/.test(detail.code)?`（错误编号：${detail.code}）`:'';
    throw new Error(message+code);
   }
   if(request.keep_recipe&&!retainedPairMatches(request,data.plan))throw new Error('这次换菜没有保留原来的另一道菜，请重试。');
   lastRequest=request;lastResult=data;render(data);destination='result-heading';
 }catch(error){$('error').textContent=error.name==='AbortError'?'等待超时，请稍后重试。':error instanceof TypeError?'连接中断，请检查网络和服务后重试。':error.message;$('error').hidden=false;}
 finally{clearTimeout(timeout);busy=false;$('meal-form').setAttribute('aria-busy','false');$('submit').disabled=false;document.querySelectorAll('form input, form select, form textarea, #ingredient-dialog input, #ingredient-dialog textarea, [data-select-category], .selected-food, #example, #choose-foods, #clear-ingredients, .swap').forEach(el=>el.disabled=false);$('clear-ingredients').disabled=!ingredients().length;$('agent-mode').disabled=!modelReady;$('status-message').textContent='';$('status-message').className='';setWorkspace('menu');reveal(destination);}
}
function quantity(item){return `${item.amount} ${item.unit}`;}
function render(result){
 const p=result.plan;
 $('empty').hidden=true;$('results').hidden=false;
 $('results').innerHTML=`<div class="result-top"><div><h2 id="result-heading" tabindex="-1">今晚，就吃这两道。</h2><p>${p.people} 人份 · 顺序烹饪约 ${p.minutes} 分钟 · 用上 ${p.used.length} 种现有食材</p></div><span class="mode-badge">${result.mode==='demo'?'本地规则 · 未调用模型':'smolagents · 实际运行'}</span></div>
 <div class="result-tabs" role="tablist" aria-label="菜单结果"><button type="button" role="tab" id="tab-menu" data-result-tab="menu" aria-controls="panel-menu" aria-selected="true">今晚菜单</button><button type="button" role="tab" id="tab-shopping" data-result-tab="shopping" aria-controls="panel-shopping" aria-selected="false" tabindex="-1">食材清单</button><button type="button" role="tab" id="tab-agent" data-result-tab="agent" aria-controls="panel-agent" aria-selected="false" tabindex="-1">${result.mode==='agent'?'Agent 图解':'示例图解'}</button></div>
 <section id="panel-menu" class="result-panel" role="tabpanel" aria-labelledby="tab-menu"><div class="dish-grid">${p.dishes.map(d=>`<article class="dish-card"><div class="dish-visual"><span aria-hidden="true">${esc(d.emoji)}</span><small>约 ${esc(d.minutes)} 分钟</small></div><div class="dish-body"><h3>${esc(d.name)}</h3><div class="food-line">${d.ingredients.slice(0,3).map(i=>`${esc(i.name)} ${esc(quantity(i))}${i.available?'':' <b>需补买</b>'}`).join('<br>')}${d.ingredients.length>3?`<p class="more-foods">另有 ${d.ingredients.length-3} 种，查看完整用量 ↓</p>`:''}</div><button type="button" class="secondary recipe-open" data-recipe-id="${esc(d.id)}">查看做法与完整用量 ↗</button><button type="button" class="swap" data-id="${esc(d.id)}" aria-label="更换${esc(d.name)}，保留另一道菜">不想吃这道，换一道 ↗</button></div></article>`).join('')}</div><p class="menu-note">食材清单和 Agent 图解在上方页签；用餐主食另行准备。</p></section>
 <section id="panel-shopping" class="result-panel shopping" role="tabpanel" aria-labelledby="tab-shopping" hidden><div class="shopping-head"><h3>做饭前，核一下清单</h3><div class="list-actions"><button id="copy-list" class="link-button" type="button">复制清单</button><button id="download" class="link-button" type="button">下载清单 ↓</button></div></div><p id="copy-status" role="status" aria-live="polite"></p><textarea id="copy-fallback" aria-label="可手动复制的清单" readonly hidden></textarea>
 ${p.shopping.length?`<ul>${p.shopping.map(i=>`<li><label><input type="checkbox">${esc(i.name)} <strong>${esc(quantity(i))}</strong></label></li>`).join('')}</ul>`:'<p class="good">✓ 主要食材都有，不用补买新品种。</p>'}
 <p><strong>已有的，也核一下数量：</strong>${p.stock_check.map(i=>`${esc(i.name)} ${esc(quantity(i))}`).join('、')}。</p><p><strong>厨房基础调味：</strong>${p.staples.map(esc).join('、')}，缺少的请另行补齐。</p>${p.unused.length?`<p>这次没用到：${p.unused.map(esc).join('、')}。</p>`:''}<p>${esc(p.note)}</p></section>
 <section id="panel-agent" class="result-panel" role="tabpanel" aria-labelledby="tab-agent" hidden>${renderJourney(result)}</section>`;
 document.querySelectorAll('[data-result-tab]').forEach(b=>b.addEventListener('click',()=>setResultTab(b.dataset.resultTab)));
 bindTabKeys('[data-result-tab]','resultTab',['menu','shopping','agent'],setResultTab);
 document.querySelectorAll('[data-recipe-id]').forEach(b=>b.addEventListener('click',()=>openRecipe(b.dataset.recipeId)));
 setResultTab('menu');
 document.querySelectorAll('.swap').forEach(b=>b.addEventListener('click',()=>swapDish(b.dataset.id)));
 $('download').addEventListener('click',download);
 $('copy-list').addEventListener('click',copyList);
}
function setResultTab(key){
 if(!['menu','shopping','agent'].includes(key))return;
 for(const name of ['menu','shopping','agent']){
  $(`panel-${name}`).hidden=name!==key;$(`tab-${name}`).setAttribute('aria-selected',String(name===key));$(`tab-${name}`).setAttribute('tabindex',name===key?'0':'-1');
 }
}
function openRecipe(id){
 if(busy||!lastResult)return;
 const d=lastResult.plan.dishes.find(d=>d.id===id);if(!d)return;
 $('recipe-content').innerHTML=`<header class="dialog-heading"><div><p class="eyebrow">${esc(lastResult.plan.people)} 人份 · 约 ${esc(d.minutes)} 分钟</p><h2 id="recipe-dialog-title">${esc(d.name)}</h2></div><button type="button" class="icon-button" id="close-recipe" aria-label="关闭菜谱">×</button></header><h3>准备这些食材</h3><ul class="recipe-foods">${d.ingredients.map(i=>`<li>${esc(i.name)} <strong>${esc(quantity(i))}</strong>${i.available?'':' · 需补买'}</li>`).join('')}</ul><p class="tiny">基础调味：${(d.staples||[]).map(esc).join('、')||'参照清单核对'}。</p><h3>一步步做</h3><ol>${d.steps.map(s=>`<li>${esc(s)}</li>`).join('')}</ol><p class="recipe-source">${esc(d.source)}</p>`;
 $('close-recipe').addEventListener('click',()=>$('recipe-dialog').close());$('recipe-dialog').showModal();
}
function journeyIcon(index){
 const drawings=[
  '<path d="M12 14h18c5 0 8 3 8 7v30c-3-4-6-5-10-5H12zM38 21c0-4 3-7 8-7h8v32h-6c-4 0-7 1-10 5M18 24h10m-10 8h10"/><circle cx="45" cy="21" r="8"/><path d="m50 27 6 6"/>',
  '<path d="M10 30h42v10c0 9-8 15-21 15S10 49 10 40zM52 35h8M16 24h29M22 10c-5 5 5 7 0 12m10-14c-5 5 5 7 0 12m10-10c-5 5 5 7 0 12"/>',
  '<rect x="15" y="12" width="36" height="44" rx="5"/><path d="M25 12V8h16v4M23 25l3 3 5-6m5 4h8M23 39l3 3 5-6m5 4h8"/>',
  '<circle cx="34" cy="33" r="22"/><circle cx="34" cy="33" r="15"/><path d="M4 14v13m5-13v13M4 23h5m-3 4v28M60 14v41M26 34l6 6 12-14"/>'
 ];return `<svg viewBox="0 0 64 64" aria-hidden="true">${drawings[index]}</svg>`;
}
function journeySteps(result){
 const p=result.plan,trace=Array.isArray(result.trace)?result.trace:[];
 if(result.mode!=='agent')return [
  {title:'① 读取食材',text:`这次用上 ${p.used.length} 种现有食材。`,evidence:'本地输入',icon:0},
  {title:'② 规则选菜',text:trace.find(t=>t.kind==='demo')?.detail||'未记录本地比较过程。',evidence:'没有调用大模型',icon:1},
  {title:'③ 核对清单',text:`核对用量和时间，预计合计 ${p.minutes} 分钟。`,evidence:trace.some(t=>t.kind==='validation')?'本地程序检查':'未记录校验步骤',icon:2},
 ];
 const lookups=trace.filter(t=>t.tool==='find_recipes'&&Array.isArray(t.result));
 const lookup=lookups.at(-1);
 const registered=new Set(trace.flatMap(t=>t.result?.valid&&t.tool==='draft_recipe'?[t.result.recipe?.id]:t.result?.valid&&t.tool==='compose_menu'?t.result.recipe_ids||[]:[]));
 const retainedIds=new Set(trace.filter(t=>t.kind==='retained').map(t=>t.recipe_id));
 const retained=p.dishes.filter(d=>retainedIds.has(d.id));
 const changed=p.dishes.filter(d=>!retainedIds.has(d.id));
 const fresh=changed.filter(d=>d.id.startsWith('gen-'));
 const drafted=fresh.length>0&&fresh.every(d=>registered.has(d.id));
 const referenceIds=new Set(lookup?.result.map(r=>r.id)||[]);
 const referenced=changed.length>0&&changed.every(d=>referenceIds.has(d.id));
 const pair=p.dishes.map(d=>d.id).sort().join('|');
 const evaluated=trace.some(t=>t.tool==='evaluate_menu'&&t.result?.valid&&((t.arguments||t.result.plan?.dishes?.map(d=>d.id)||[]).slice().sort().join('|')===pair));
 const checked=evaluated&&trace.some(t=>t.kind==='validation');
 const codeCount=trace.filter(t=>t.kind==='code').length;
 return [
  {title:'① 查菜谱参考',text:lookup?`查到 ${lookup.result.length} 道本地参考菜；不合适时可设计新菜。`:'本次没有可用的查询记录。',evidence:lookup?'实际调用了查询工具':'未记录此步骤',icon:0},
  {title:retained.length===1?'② 只换一道菜':'② 搭配两道菜',text:retained.length?(drafted?`保留 ${retained.length} 道菜，围绕现有食材拟定了 ${fresh.length} 道新菜，再提交工具检查。`:referenced?`保留 ${retained.length} 道菜，从参考菜谱中替换了 ${changed.length} 道菜。`:`保留 ${retained.length} 道菜，未找到替换菜的登记或选择记录。`):drafted?`围绕现有食材拟定了 ${fresh.length} 道新菜，再提交工具检查。`:referenced?'从参考菜谱中选择了这两道菜。':'未找到这两道菜的登记或选择记录。',evidence:codeCount?`CodeAgent 实际执行 ${codeCount} 段代码`:'未记录代码执行步骤',icon:1},
  {title:'③ 检查这一餐',text:evaluated?`检查食材、人数用量和总时间，预计 ${p.minutes} 分钟。`:'没有找到这组菜的成功评估记录。',evidence:evaluated?'这组菜单通过程序评估':'未记录成功评估',icon:2},
  {title:'④ 整理成菜单',text:checked?'应用再独立核对，整理出做法和食材清单。':'没有完整的最终核对记录。',evidence:checked?'完成最终程序校验':'未记录最终校验',icon:3},
 ];
}
function renderJourney(result){
 const trace=Array.isArray(result.trace)?result.trace:[];
 const rejected=trace.filter(t=>['draft_recipe','compose_menu','evaluate_menu'].includes(t.tool)&&t.result?.valid===false).length;
 const recovered=trace.some(t=>t.kind==='recovery');
 return `<section class="journey"><h3>${result.mode==='agent'?'这次 Agent 实际做了什么？':'示例是怎么选出来的？'}</h3><p class="journey-lead">${result.mode==='agent'?'smolagents 让模型调用工具、执行代码，再把菜单交给程序核对。下面是这次实际记录的图解。':'这次由本地规则选菜，没有调用大模型，也没有 Agent 运行。'}</p><ol class="journey-grid">${journeySteps(result).map(step=>`<li class="journey-step">${journeyIcon(step.icon)}<h4>${esc(step.title)}</h4><p>${esc(step.text)}</p><span class="step-evidence">${esc(step.evidence)}</span></li>`).join('')}</ol>${rejected?`<p class="journey-note">中间有 ${rejected} 次提交未通过，模型收到工具反馈后继续调整。</p>`:''}${recovered?'<p class="journey-note">最后回答格式不完整，保留本次已评估的组合，再次校验后呈现。</p>':''}<p class="journey-note">这是完成后的执行回顾；程序校验不等于专业烹饪或营养审核。</p><details class="technical-record"><summary>开发者记录 · 代码与工具数据</summary>${trace.map(t=>`<div class="trace-entry"><h4>${esc(t.title)}</h4><p>${esc(t.detail||'')}</p>${t.code?`<pre><code>${esc(t.code)}</code></pre>`:''}${t.result?`<details><summary>查看工具返回数据</summary><pre>${esc(JSON.stringify(t.result,null,2))}</pre></details>`:''}</div>`).join('')}</details></section>`;
}
function listText(){
 const p=lastResult.plan;
 const lines=['冰箱有招 · 今晚的清单',`${p.people} 人份，顺序烹饪约 ${p.minutes} 分钟`,'',...p.dishes.map(d=>d.name),'','需要补买：',...(p.shopping.length?p.shopping.map(i=>`${i.name} ${quantity(i)}`):['主要食材无需新增品种。']),'','已有数量待核实：',...p.stock_check.map(i=>`${i.name} ${quantity(i)}`),'','基础调味：'+p.staples.join('、'),'',p.note];
 return lines.join('\n');
}
async function copyList(){
 const text=listText();
 try{
  await navigator.clipboard.writeText(text);
  $('copy-status').textContent='已复制，可以粘贴到备忘录或聊天里。';
  $('copy-fallback').hidden=true;
 }catch{
  $('copy-status').textContent='浏览器未允许自动复制，请长按下方清单复制，或使用下载。';
  $('copy-fallback').hidden=false;$('copy-fallback').value=text;
  $('copy-fallback').focus();$('copy-fallback').select();
 }
}
function download(){
 const url=URL.createObjectURL(new Blob(['\uFEFF'+listText()],{type:'text/plain;charset=utf-8'}));const a=document.createElement('a');a.href=url;a.download='冰箱有招-今晚清单.txt';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
}
let modelReady=false;
fetch('/api/status').then(r=>{if(!r.ok)throw new Error();return r.json();}).then(data=>{modelReady=data.model_ready;$('agent-mode').disabled=busy||!modelReady;if(modelReady&&!modeChosen&&!busy&&!lastResult)$('agent-mode').checked=true;$('model-status').textContent=modelReady?'模型配置已填，安排时验证连接。':'模型尚未配置，可以先用示例体验。';}).catch(()=>{$('model-status').textContent='暂时连接不到服务，请稍后刷新。';});
