// Exercise the shipped script with DOM/network substitutes; no browser dependency.
const {test} = require('node:test');
const assert = require('node:assert/strict');
const {readFileSync} = require('node:fs');
const {resolve} = require('node:path');
const vm = require('node:vm');
const source = readFileSync(resolve(__dirname, '../fridge/static/app.js'), 'utf8');
const page = readFileSync(resolve(__dirname, '../fridge/static/index.html'), 'utf8');

function setup(model_ready=false, withPicker=false) {
  const nodes = new Map();
  const node = id => {
    if (!nodes.has(id)) nodes.set(id, {
      value:'', hidden:false, disabled:false, checked:false, dataset:{}, handlers:{},
      addEventListener(type, handler){this.handlers[type]=handler;},
      setAttribute(name,value){this[name]=value;},
      select(){this.selected=true;},
      showModal(){this.open=true;},
      close(){this.open=false;},
      focus(){this.focused=true;},
      scrollIntoView(){
        this.scrolled=true;
        this.loadingAtScroll=node('status-message').className;
      },
    });
    return nodes.get(id);
  };
  node('ingredients').value='鸡蛋、番茄、白菜';
  node('people').value='2';
  node('minutes').value='30';
  node('mode').value='demo';
  // Build only the picker controls from the shipped HTML, so category membership
  // and actual click/change bindings are covered without a separate fixture list.
  const categories={};
  if(withPicker){
    for(const [,key,markup] of page.matchAll(/<section class="ingredient-category" id="food-([^"]+)"[^>]*>([\s\S]*?)<\/section>/g)){
      const group=node('food-'+key);
      const choices=[...markup.matchAll(/data-ingredient="([^"]+)"/g)].map(([,food])=>{
        const input=node('ingredient-'+food);input.dataset.ingredient=food;return input;
      });
      const button=node('select-'+key);
      const name=markup.match(/data-select-category="([^"]+)" data-category-name="([^"]+)"/);
      assert.equal(name?.[1],key,'Each category must expose its own bulk-selection button');
      button.dataset={selectCategory:key,categoryName:name[2]};
      group.querySelector=selector=>selector==='.category-count'?node('count-'+key):button;
      group.querySelectorAll=selector=>selector==='input:checked'?choices.filter(input=>input.checked):choices;
      categories[key]={group,choices,button};
    }
    assert.equal(Object.keys(categories).length,5);
  }
  const context = vm.createContext({
    document:{
      getElementById:node,
      querySelector:()=>node('mode'),
      querySelectorAll:selector=>{
        if(selector==='.ingredient-category')return Object.values(categories).map(c=>c.group);
        if(selector==='[data-ingredient]')return Object.values(categories).flatMap(c=>c.choices);
        if(selector==='[data-select-category]')return Object.values(categories).map(c=>c.button);
        if(selector.includes('[data-select-category]'))return [...Object.values(categories).map(c=>c.button),node('clear-ingredients')];
        return [];
      },
    },
    fetch:async()=>({ok:true,json:async()=>({model_ready})}),
    setTimeout, clearTimeout, AbortController, Blob, URL, navigator:{},
  });
  vm.runInContext(source,context);
  return {node,context,categories,run:expression=>vm.runInContext(expression,context)};
}

const result = {
  mode:'demo', trace:[],
  plan:{
    people:2,minutes:22,used:['鸡蛋'],unused:[],shopping:[],
    stock_check:[{name:'鸡蛋',amount:1,unit:'个'}],staples:['盐'],note:'核对数量',
    dishes:[{id:'soup',name:'<img src=x onerror=alert(1)>',emoji:'🥣',minutes:12,
      ingredients:[],steps:['烧开'],source:'示例'}],
  },
};
const generatedDish=(number,name='菜'+number)=>({
  id:'gen-'+String(number).padStart(16,'0'),name,emoji:'🥣',minutes:10,vegetarian:true,servings:2,
  ingredients:[{name:'鸡蛋',amount:4,unit:'个',available:true}],
  staples:['盐'],steps:['充分做熟。'],source:'本次拟定的菜谱',
});
const pairResult=dishes=>({...result,mode:'agent',plan:{...result.plan,people:4,dishes}});

for(const replaceIndex of [0,1]){
  test(`single-dish replacement in slot ${replaceIndex} sends the current other dish and preserves its slot`,async()=>{
    const app=setup();app.node('people').value='4';
    const original=pairResult([generatedDish(1),generatedDish(2)]);
    const next=pairResult(original.plan.dishes.map((dish,index)=>index===replaceIndex?generatedDish(3):dish));
    const responses=[original,next],requests=[];
    app.context.fetch=async(url,options)=>{requests.push(JSON.parse(options.body));return {ok:true,json:async()=>responses.shift()};};
    await app.run('run(readForm())');
    await app.run(`swapDish("${original.plan.dishes[replaceIndex].id}")`);
    const request=requests[1],kept=original.plan.dishes[1-replaceIndex];
    assert.equal(request.keep_index,1-replaceIndex);
    assert.deepEqual(request.keep_recipe,{
      id:kept.id,name:kept.name,minutes:kept.minutes,vegetarian:kept.vegetarian,
      ingredients:kept.ingredients.map(({name,amount,unit})=>({name,amount,unit})),
      staples:kept.staples,steps:kept.steps,servings:4,
    });
    assert.deepEqual(request.exclude_ids,[original.plan.dishes[replaceIndex].id]);
    assert.deepEqual(request.exclude_names,[original.plan.dishes[replaceIndex].name]);
    assert.equal(app.run(`lastResult.plan.dishes[${1-replaceIndex}].id`),kept.id);
    assert.equal(app.run(`lastResult.plan.dishes[${replaceIndex}].id`),generatedDish(3).id);
    assert.match(app.node('results').innerHTML,/换一道/);
  });
}

test('successive left and right replacements always retain the latest opposite dish',async()=>{
  const app=setup();app.node('people').value='4';
  const a=generatedDish(1),b=generatedDish(2),c=generatedDish(3),d=generatedDish(4),e=generatedDish(5);
  const responses=[pairResult([a,b]),pairResult([c,b]),pairResult([d,b]),pairResult([d,e])],requests=[];
  app.context.fetch=async(url,options)=>{requests.push(JSON.parse(options.body));return {ok:true,json:async()=>responses.shift()};};
  await app.run('run(readForm())');
  await app.run(`swapDish("${a.id}")`);
  await app.run(`swapDish("${c.id}")`);
  await app.run(`swapDish("${b.id}")`);
  assert.equal(requests[2].keep_recipe.id,b.id);
  assert.equal(requests[3].keep_recipe.id,d.id);
  assert.equal(requests[3].keep_index,0);
  assert.deepEqual(requests[3].exclude_ids,[a.id,c.id,b.id]);
  assert.deepEqual(requests[3].exclude_names,[a.name,c.name,b.name]);
  assert.deepEqual(JSON.parse(app.run('JSON.stringify(lastResult.plan.dishes.map(d=>d.id))')),[d.id,e.id]);
});

for(const failure of ['http','changed-other-dish','incomplete-menu']){
  test(`failed single-dish replacement (${failure}) retains the full previous menu`,async()=>{
    const app=setup();app.node('people').value='4';
    const original=pairResult([generatedDish(1),generatedDish(2)]);
    app.context.fetch=async()=>({ok:true,json:async()=>original});
    await app.run('run(readForm())');
    const html=app.node('results').innerHTML;
    const invalid=failure==='changed-other-dish'?pairResult([generatedDish(3),generatedDish(4)]):pairResult([generatedDish(3)]);
    app.context.fetch=async()=>failure==='http'?{ok:false,json:async()=>({detail:'保留另一道菜时没有合适的替代，请调整条件后重试。'})}:{ok:true,json:async()=>invalid};
    await app.run(`swapDish("${original.plan.dishes[0].id}")`);
    assert.equal(app.node('results').innerHTML,html);
    assert.equal(app.run('lastResult.plan.dishes[0].id'),original.plan.dishes[0].id);
    assert.equal(app.run('lastResult.plan.dishes[1].id'),original.plan.dishes[1].id);
    assert.equal(app.run('Boolean(lastRequest.keep_recipe)'),false);
    assert.equal(app.node('error').hidden,false);
    assert.equal(app.node('submit').disabled,false);
    if(failure!=='http')assert.match(app.node('error').textContent,/没有保留原来的另一道菜/);
  });
}

for(const field of ['name','minutes','vegetarian','ingredients','steps','staples','people']){
  test(`two-dish replacement rejects changed retained ${field} and keeps both old cards`,async()=>{
    const app=setup();app.node('people').value='4';
    const original=pairResult([generatedDish(1),generatedDish(2)]);
    app.context.fetch=async()=>({ok:true,json:async()=>original});
    await app.run('run(readForm())');
    const html=app.node('results').innerHTML;
    const altered=JSON.parse(JSON.stringify(original.plan.dishes[1]));
    if(field==='ingredients')altered.ingredients[0].amount=999;
    else if(field==='steps')altered.steps=['偷偷改掉的做法。'];
    else if(field==='staples')altered.staples=['糖'];
    else if(field==='vegetarian')altered.vegetarian=false;
    else if(field==='minutes')altered.minutes=11;
    else if(field==='name')altered.name='偷偷改掉的保留菜';
    const invalid=pairResult([generatedDish(3),altered]);
    if(field==='people')invalid.plan.people=6;
    app.context.fetch=async()=>({ok:true,json:async()=>invalid});
    await app.run(`swapDish("${original.plan.dishes[0].id}")`);
    assert.equal(app.node('results').innerHTML,html);
    assert.deepEqual(JSON.parse(app.run('JSON.stringify(lastResult)')),original);
    assert.equal(app.node('error').hidden,false);
    assert.equal(app.node('submit').disabled,false);
    assert.match(app.node('error').textContent,/没有保留原来的另一道菜/);
  });
}

for(const invalidDish of ['excluded-id','excluded-name','duplicate-id','missing-id','blank-id']){
  test(`two-dish replacement rejects ${invalidDish} and keeps the full previous menu`,async()=>{
    const app=setup();app.node('people').value='4';
    const original=pairResult([generatedDish(1),generatedDish(2)]);
    app.context.fetch=async()=>({ok:true,json:async()=>original});
    await app.run('run(readForm())');
    const html=app.node('results').innerHTML;
    const replacement=generatedDish(3);
    if(invalidDish==='excluded-id')replacement.id=original.plan.dishes[0].id;
    else if(invalidDish==='excluded-name')replacement.name=original.plan.dishes[0].name;
    else if(invalidDish==='duplicate-id')replacement.id=original.plan.dishes[1].id;
    else if(invalidDish==='missing-id')delete replacement.id;
    else replacement.id='   ';
    app.context.fetch=async()=>({ok:true,json:async()=>pairResult([replacement,original.plan.dishes[1]])});
    await app.run(`swapDish("${original.plan.dishes[0].id}")`);
    assert.equal(app.node('results').innerHTML,html);
    assert.deepEqual(JSON.parse(app.run('JSON.stringify(lastResult)')),original);
    assert.equal(app.node('error').hidden,false);
    assert.equal(app.node('submit').disabled,false);
  });
}

for(const people of [1,2,3,4,5,6]){
  test(`fixed menu at ${people} people displays exactly two recipe cards and keeps the pair protocol`,async()=>{
    const app=setup();app.node('people').value=String(people);
    const original=pairResult([generatedDish(1),generatedDish(2)]);original.plan.people=people;
    let sent;
    app.context.fetch=async(url,options)=>{sent=JSON.parse(options.body);return {ok:true,json:async()=>original};};
    await app.run('run(readForm())');
    assert.equal(sent.people,people);
    assert.equal((app.node('results').innerHTML.match(/class="dish-card"/g)||[]).length,2);
    assert.match(app.node('results').innerHTML,/今晚，就吃这两道/);
    const request=JSON.parse(app.run(`JSON.stringify(replacementRequest("${original.plan.dishes[0].id}"))`));
    assert.equal(request.keep_recipe.servings,people);
    assert.equal(request.keep_index,1);
    assert.equal('menu_count' in request,false);
    assert.equal('keep_recipes' in request,false);
  });
}

test('replacement exclusion history remains bounded and includes the latest rejected dish',async()=>{
  const app=setup();const original=pairResult([generatedDish(1),generatedDish(2)]);
  app.context.fetch=async()=>({ok:true,json:async()=>original});
  await app.run('run(readForm())');
  app.run('lastRequest.exclude_ids=Array.from({length:20},(_,i)=>"gen-"+String(i+30).padStart(16,"0"));lastRequest.exclude_names=Array.from({length:20},(_,i)=>"旧菜"+i)');
  const request=JSON.parse(app.run(`JSON.stringify(replacementRequest("${original.plan.dishes[0].id}"))`));
  assert.equal(request.exclude_ids.length,20);assert.equal(request.exclude_names.length,20);
  assert.equal(request.exclude_ids.at(-1),original.plan.dishes[0].id);
  assert.equal(request.exclude_names.at(-1),original.plan.dishes[0].name);
});

test('a pending single-dish replacement explains retention and ignores further swap clicks',async()=>{
  const app=setup();const original=pairResult([generatedDish(1),generatedDish(2)]);
  app.context.fetch=async()=>({ok:true,json:async()=>original});
  await app.run('run(readForm())');
  let finish,calls=0;
  app.context.fetch=()=>{calls++;return new Promise(resolve=>{finish=resolve;});};
  const pending=app.run(`swapDish("${original.plan.dishes[0].id}")`);
  assert.match(app.node('status-message').textContent,/保留另一道菜/);
  await app.run(`swapDish("${original.plan.dishes[1].id}")`);
  assert.equal(calls,1);
  finish({ok:true,json:async()=>pairResult([generatedDish(3),original.plan.dishes[1]])});
  await pending;
});

test('empty input focuses the actionable error without requesting a plan',async()=>{
  const app=setup();
  let requests=0;
  app.context.fetch=async()=>{requests++;throw new Error('unexpected');};
  await app.run('run({ingredients:[]})');
  assert.equal(requests,0);
  assert.equal(app.node('workbench').dataset.view,'menu');
  assert.match(app.node('error').textContent,/至少一种/);
  assert.equal(app.node('error').focused,true);
  assert.equal(app.node('error').scrolled,true);
});

test('successful result escapes recipe text and moves focus to the menu',async()=>{
  const app=setup();
  app.context.fetch=async()=>({ok:true,json:async()=>result});
  await app.run('run(readForm())');
  assert.equal(app.node('results').hidden,false);
  assert.match(app.node('results').innerHTML,/&lt;img/);
  assert.doesNotMatch(app.node('results').innerHTML,/<img/);
  assert.equal(app.node('result-heading').focused,true);
  assert.equal(app.node('result-heading').scrolled,true);
  assert.equal(app.node('result-heading').loadingAtScroll,'');
  assert.equal(app.node('submit').disabled,false);
  assert.equal(app.node('agent-mode').disabled,true);
});

test('failed replacement keeps the last menu and releases the form for retry',async()=>{
  const app=setup();
  app.context.fetch=async()=>({ok:true,json:async()=>result});
  await app.run('run(readForm())');
  const previous=app.node('results').innerHTML;
  app.context.fetch=async()=>({ok:false,json:async()=>({detail:'请增加时间后重试。'})});
  await app.run('run({...readForm(),exclude_ids:["soup"]})');
  assert.equal(app.node('results').innerHTML,previous);
  assert.equal(app.node('error').textContent,'请增加时间后重试。');
  assert.equal(app.node('error').focused,true);
  assert.equal(app.node('error').loadingAtScroll,'');
  assert.equal(app.node('submit').disabled,false);
});

test('categorized failure shows its safe reason and code while retaining the previous menu',async()=>{
  const app=setup();
  app.context.fetch=async()=>({ok:true,json:async()=>result});
  await app.run('run(readForm())');
  const previous=app.node('results').innerHTML;
  app.context.fetch=async()=>({ok:false,json:async()=>({detail:{message:'这次菜单没有完成检查，请重试。',code:'menu_incomplete'}})});
  await app.run('run({...readForm(),mode:"agent"})');
  assert.equal(app.node('error').textContent,'这次菜单没有完成检查，请重试。（错误编号：menu_incomplete）');
  assert.equal(app.node('results').innerHTML,previous);
  assert.equal(app.node('submit').disabled,false);
});

test('waiting scrolls into view and prevents duplicate submissions',async()=>{
  const app=setup();
  let finish, calls=0;
  app.context.fetch=()=>{calls++;return new Promise(resolve=>{finish=resolve;});};
  const pending=app.run('run({...readForm(),mode:"agent"})');
  assert.equal(app.node('status-message').textContent,'正在用你选的食材搭配两道家常菜，请稍等一会儿……');
  assert.equal(app.node('status-message').focused,true);
  assert.equal(app.node('meal-form')['aria-busy'],'true');
  await app.run('run(readForm())');
  assert.equal(calls,1);
  finish({ok:true,json:async()=>result});
  await pending;
  assert.equal(app.node('meal-form')['aria-busy'],'false');
});

test('phone clipboard failure exposes a selectable complete list',async()=>{
  const app=setup();
  app.context.fetch=async()=>({ok:true,json:async()=>result});
  await app.run('run(readForm())');
  await app.run('copyList()');
  assert.equal(app.node('copy-fallback').hidden,false);
  assert.equal(app.node('copy-fallback').selected,true);
  assert.match(app.node('copy-fallback').value,/已有数量待核实/);
  assert.match(app.node('copy-fallback').value,/鸡蛋 1 个/);
  assert.match(app.node('copy-status').textContent,/长按/);
});

test('clipboard success copies the list and dismisses manual fallback',async()=>{
  const app=setup();
  let copied;
  app.context.navigator.clipboard={writeText:async text=>{copied=text;}};
  app.context.fetch=async()=>({ok:true,json:async()=>result});
  await app.run('run(readForm())');
  await app.run('copyList()');
  assert.match(copied,/冰箱有招/);
  assert.equal(app.node('copy-fallback').hidden,true);
  assert.match(app.node('copy-status').textContent,/已复制/);
});

test('request timeout restores controls and provides an actionable message',async()=>{
  const app=setup();
  app.context.fetch=async()=>{const error=new Error();error.name='AbortError';throw error;};
  await app.run('run(readForm())');
  assert.match(app.node('error').textContent,/超时/);
  assert.equal(app.node('submit').disabled,false);
});

test('configured model is selected by default without claiming a verified connection',async()=>{
  const app=setup(true);
  await new Promise(resolve=>setImmediate(resolve));
  assert.equal(app.node('agent-mode').checked,true);
  assert.equal(app.node('agent-mode').disabled,false);
  assert.match(app.node('model-status').textContent,/安排时验证连接/);
});

test('late status response preserves a mode the user has already chosen',async()=>{
  const app=setup(true);
  app.run('modeChosen=true');
  await new Promise(resolve=>setImmediate(resolve));
  assert.equal(app.node('agent-mode').checked,false);
});

test('category selection supports multiple ingredients and removing tags',()=>{
  const app=setup();
  app.node('ingredients').value='';
  app.run("setPickedFood('五花肉',true);setPickedFood('蒜苔',true);setPickedFood('丝瓜',true);setPickedFood('蒜苔',true)");
  assert.equal(app.node('ingredients').value,'五花肉、蒜苔、丝瓜');
  assert.match(app.node('selected-ingredients').innerHTML,/移除五花肉/);
  app.run("setPickedFood('蒜苔',false)");
  assert.equal(app.node('ingredients').value,'五花肉、丝瓜');
  assert.equal(app.node('results').hidden,true);
});

test('manual ingredients normalize aliases, escape markup and stay in the request',()=>{
  const app=setup();
  app.node('ingredients').value='西红柿，番茄、莴笋；<img src=x>';
  app.run('syncPicker()');
  assert.equal(app.run('ingredients().length'),3);
  assert.match(app.node('selected-ingredients').innerHTML,/莴笋/);
  assert.doesNotMatch(app.node('selected-ingredients').innerHTML,/<img/);
  assert.equal(app.run('readForm().ingredients[0]'),'番茄');
});

test('vegetarian selection warns about selected meat without changing preference',()=>{
  const app=setup();
  app.node('vegetarian').checked=true;
  app.node('ingredients').value='五花肉、蒜苔、丝瓜';
  app.run('syncPicker()');
  assert.match(app.node('diet-hint').textContent,/不会使用/);
  assert.equal(app.node('vegetarian').checked,true);
});

test('selection is locked while a menu is running',()=>{
  const app=setup();
  app.run("busy=true;setPickedFood('五花肉',true)");
  assert.equal(app.node('ingredients').value,'鸡蛋、番茄、白菜');
});

test('clear removes preset and custom foods, resets all picker state and discards the old menu',()=>{
  const app=setup(false,true);
  app.node('ingredients').value='五花肉、西红柿、莴笋';
  app.node('people').value='4';app.node('minutes').value='45';app.node('vegetarian').checked=true;
  app.run('syncPicker();setPickerStatus("一次最多选择 40 种食材。");lastRequest=readForm();lastResult={plan:{}}');
  app.node('results').hidden=false;app.node('error').hidden=false;
  app.node('clear-ingredients').handlers.click();
  assert.equal(app.node('ingredients').value,'');
  assert.equal(app.node('clear-ingredients').disabled,true);
  assert.ok(Object.values(app.categories).every(c=>c.choices.every(input=>!input.checked)));
  assert.ok(Object.values(app.categories).every(c=>c.button.textContent==='全选'));
  for(const key of Object.keys(app.categories))assert.equal(app.node('count-'+key).textContent,'');
  assert.match(app.node('picker-total').textContent,/已选 0 种/);
  assert.doesNotMatch(app.node('selected-ingredients').innerHTML,/data-remove-food/);
  assert.equal(app.node('picker-status').textContent,'');
  assert.equal(app.node('picker-feedback').textContent,'');
  assert.equal(app.node('diet-hint').textContent,'');
  assert.equal(app.node('results').hidden,true);assert.equal(app.node('empty').hidden,false);
  assert.equal(app.node('error').hidden,true);
  assert.equal(app.run('lastRequest'),null);assert.equal(app.run('lastResult'),null);
  assert.equal(app.node('people').value,'4');assert.equal(app.node('minutes').value,'45');
  assert.equal(app.node('vegetarian').checked,true);
  assert.equal(app.node('choose-foods').focused,true);
});

test('clear action follows empty and refilled selection state',()=>{
  const app=setup(false,true);
  app.node('ingredients').value='';app.node('ingredients').handlers.input();
  assert.equal(app.node('clear-ingredients').disabled,true);
  app.run('setPickedFood("鸡蛋",true)');
  assert.equal(app.node('clear-ingredients').disabled,false);
  app.node('clear-ingredients').handlers.click();
  assert.equal(app.node('clear-ingredients').disabled,true);
  app.node('ingredients').value='莴笋';app.node('ingredients').handlers.input();
  assert.equal(app.node('clear-ingredients').disabled,false);
});

test('clear is disabled and guarded during generation and available after failure',async()=>{
  const app=setup(false,true);
  let finish;
  app.context.fetch=()=>new Promise(resolve=>{finish=resolve;});
  const pending=app.run('run(readForm())');
  assert.equal(app.node('clear-ingredients').disabled,true);
  app.node('clear-ingredients').handlers.click();
  assert.equal(app.node('ingredients').value,'鸡蛋、番茄、白菜');
  finish({ok:false,json:async()=>({detail:'请重试。'})});
  await pending;
  assert.equal(app.node('clear-ingredients').disabled,false);
  app.node('clear-ingredients').handlers.click();
  assert.equal(app.node('ingredients').value,'');
});

for(const key of ['meat','vegetables','eggs','seafood','grains']){
  test(`bulk selection in ${key} preserves other categories and custom foods`,()=>{
    const app=setup(false,true);
    app.node('ingredients').value='西红柿、鸡蛋、莴笋';
    app.run('syncPicker()');
    app.node('results').hidden=false;
    const {choices,button}=app.categories[key];
    const foods=choices.map(input=>input.dataset.ingredient);
    const expected=[...new Set(['番茄','鸡蛋','莴笋',...foods])];
    button.handlers.click();
    assert.deepEqual(JSON.parse(app.run('JSON.stringify(readForm().ingredients)')),expected);
    assert.ok(choices.every(input=>input.checked));
    assert.equal(button.textContent,'取消全选');
    assert.equal(button['aria-label'],'取消全选'+button.dataset.categoryName);
    assert.equal(app.node('count-'+key).textContent,`已选 ${foods.length}`);
    assert.match(app.node('picker-total').textContent,new RegExp(`已选 ${expected.length} 种`));
    assert.equal(app.node('results').hidden,true);
    button.handlers.click();
    assert.deepEqual(JSON.parse(app.run('JSON.stringify(ingredients())')),['番茄','鸡蛋','莴笋'].filter(food=>!foods.includes(food)));
    assert.ok(choices.every(input=>!input.checked));
    assert.equal(button.textContent,'全选');
    assert.equal(app.node('count-'+key).textContent,'');
  });
}

test('manual and individual edits update the category action without duplicate aliases',()=>{
  const app=setup(false,true);
  const {choices,button}=app.categories.vegetables;
  app.node('ingredients').value=choices.map(input=>input.dataset.ingredient==='番茄'?'西红柿':input.dataset.ingredient).join('、')+'、番茄、鸡蛋';
  app.node('ingredients').handlers.input();
  assert.equal(button.textContent,'取消全选');
  choices[0].checked=false;choices[0].handlers.change();
  assert.equal(button.textContent,'全选');
  button.handlers.click();
  assert.equal(button.textContent,'取消全选');
  assert.equal(app.run('ingredients().length'),choices.length+1);
  assert.equal(app.run('ingredients().filter(food=>food==="番茄").length'),1);
  assert.ok(app.node('ingredients').value.includes('鸡蛋'));
});

test('bulk selection rejects over-limit changes atomically and allows exactly 40 foods',()=>{
  const app=setup(false,true);
  const custom=Array.from({length:36},(_,i)=>'自选'+i);
  app.node('ingredients').value=custom.join('、');
  app.run('syncPicker()');
  app.node('results').hidden=false;
  app.categories.meat.button.handlers.click();
  assert.equal(app.node('ingredients').value,custom.join('、'));
  assert.ok(app.categories.meat.choices.every(input=>!input.checked));
  assert.equal(app.node('results').hidden,false);
  assert.match(app.node('picker-feedback').textContent,/40 种/);
  assert.equal(app.node('picker-status').textContent,app.node('picker-feedback').textContent);
  app.categories.eggs.button.handlers.click();
  assert.equal(app.run('ingredients().length'),40);
  assert.equal(app.node('picker-feedback').textContent,'');
  assert.equal(app.node('results').hidden,true);
  app.categories.eggs.button.handlers.click();
  assert.equal(app.node('ingredients').value,custom.join('、'));
});

test('bulk controls are locked during generation and released after failure',async()=>{
  const app=setup(false,true);
  let finish;
  app.context.fetch=()=>new Promise(resolve=>{finish=resolve;});
  const pending=app.run('run(readForm())');
  assert.ok(Object.values(app.categories).every(c=>c.button.disabled));
  app.categories.meat.button.handlers.click();
  assert.equal(app.node('ingredients').value,'鸡蛋、番茄、白菜');
  finish({ok:false,json:async()=>({detail:'请重试。'})});
  await pending;
  assert.ok(Object.values(app.categories).every(c=>!c.button.disabled));
  app.categories.meat.button.handlers.click();
  assert.ok(app.categories.meat.choices.every(input=>input.checked));
});

test('bulk deselection can reduce an already over-limit manual list',()=>{
  const app=setup(false,true);
  const custom=Array.from({length:41},(_,i)=>'自选'+i);
  const seafood=app.categories.seafood;
  app.node('ingredients').value=[...custom,...seafood.choices.map(input=>input.dataset.ingredient)].join('、');
  app.node('ingredients').handlers.input();
  assert.equal(seafood.button.textContent,'取消全选');
  seafood.button.handlers.click();
  assert.equal(app.node('ingredients').value,custom.join('、'));
  assert.equal(seafood.button.textContent,'全选');
});

test('returning to the example clears stale picker limit feedback',()=>{
  const app=setup(false,true);
  app.node('ingredients').value=Array.from({length:40},(_,i)=>'自选'+i).join('、');
  app.node('ingredients').handlers.input();
  app.categories.meat.button.handlers.click();
  assert.match(app.node('picker-feedback').textContent,/40 种/);
  app.node('example').handlers.click();
  assert.equal(app.node('picker-feedback').textContent,'');
  assert.equal(app.node('picker-status').textContent,'');
  assert.equal(app.node('ingredients').value,'鸡蛋、番茄、白菜');
});

test('example resets the picker and focuses visible selected ingredients',()=>{
  const app=setup();
  app.node('ingredients').value='五花肉';
  app.node('example').handlers.click();
  assert.equal(app.node('ingredients').value,'鸡蛋、番茄、白菜');
  assert.match(app.node('selected-ingredients').innerHTML,/移除鸡蛋/);
  assert.equal(app.node('selected-ingredients').focused,true);
  assert.equal(app.node('vegetarian').checked,true);
});

test('result tabs expose only the chosen panel and maintain keyboard selection state',async()=>{
  const app=setup();
  app.context.fetch=async()=>({ok:true,json:async()=>result});
  await app.run('run(readForm())');
  assert.equal(app.node('workbench').dataset.view,'menu');
  app.run('setResultTab("shopping")');
  assert.equal(app.node('panel-menu').hidden,true);
  assert.equal(app.node('panel-shopping').hidden,false);
  assert.equal(app.node('panel-agent').hidden,true);
  assert.equal(app.node('tab-shopping')['aria-selected'],'true');
  assert.equal(app.node('tab-shopping').tabindex,'0');
  app.run('setResultTab("unrecognized")');
  assert.equal(app.node('panel-shopping').hidden,false);
});

test('visible desktop targets receive focus without unnecessary page scrolling',()=>{
  const app=setup();
  app.context.window={innerHeight:768};
  app.node('result-heading').getBoundingClientRect=()=>({top:180,bottom:220});
  app.run('reveal("result-heading")');
  assert.equal(app.node('result-heading').focused,true);
  assert.equal(app.node('result-heading').scrolled,undefined);
});

test('ingredient selection opens a native dialog and preserves choices across workspace views',()=>{
  const app=setup();
  app.node('choose-foods').handlers.click();
  assert.equal(app.node('ingredient-dialog').open,true);
  app.run("setPickedFood('五花肉',true);setWorkspace('menu');setWorkspace('fridge')");
  assert.match(app.node('ingredients').value,/五花肉/);
  assert.equal(app.node('show-fridge')['aria-pressed'],'true');
  assert.match(app.node('picker-total').textContent,/4 种/);
});

test('recipe dialog preserves complete ingredients and steps while escaping model content',async()=>{
  const app=setup();
  const many={...result,plan:{...result.plan,dishes:[{...result.plan.dishes[0],ingredients:Array.from({length:5},(_,i)=>({name:'食材'+i,amount:100,unit:'克',available:true})),steps:['<script>bad()</script>','煮熟']}]}};
  app.context.fetch=async()=>({ok:true,json:async()=>many});
  await app.run('run(readForm())');
  app.run('openRecipe("soup")');
  assert.equal(app.node('recipe-dialog').open,true);
  assert.match(app.node('recipe-content').innerHTML,/食材4/);
  assert.match(app.node('recipe-content').innerHTML,/&lt;script&gt;/);
  assert.doesNotMatch(app.node('recipe-content').innerHTML,/<script>/);
  assert.match(app.node('results').innerHTML,/另有 2 种/);
  app.node('close-recipe').handlers.click();
  assert.equal(app.node('recipe-dialog').open,false);
});

const agentDiagram={mode:'agent',plan:{...result.plan,dishes:[{id:'gen-a',name:'菜一'},{id:'gen-b',name:'菜二'}]},trace:[
  {tool:'find_recipes',result:[{id:'reference'}]},
  {kind:'code'}, {kind:'code'},
  {tool:'compose_menu',result:{valid:false}},
  {tool:'compose_menu',result:{valid:true,recipe_ids:['gen-a','gen-b']}},
  {tool:'evaluate_menu',arguments:['gen-b','gen-a'],result:{valid:true}},
  {kind:'validation'},
]};

test('illustrated journey derives drafted dishes, checks and repairs from actual event evidence',()=>{
  const app=setup();app.context.diagram=agentDiagram;
  const html=app.run('renderJourney(diagram)');
  assert.match(html,/拟定了 2 道新菜/);
  assert.match(html,/实际执行 2 段代码/);
  assert.match(html,/完成最终程序校验/);
  assert.match(html,/中间有 1 次提交未通过/);
  assert.match(html,/<svg/);
  assert.match(html,/开发者记录/);
});

test('replacement diagram excludes the retained generated recipe from new-dish counts',()=>{
  const app=setup();
  app.context.diagram={...agentDiagram,trace:[{kind:'retained',recipe_id:'gen-a',title:'保留另一道菜'},...agentDiagram.trace]};
  const html=app.run('renderJourney(diagram)');
  assert.match(html,/② 只换一道菜/);
  assert.match(html,/保留 1 道菜，围绕现有食材拟定了 1 道新菜/);
  assert.doesNotMatch(html,/拟定了 2 道新菜/);
});

test('replacement diagram can record a retained dish and a newly selected reference recipe',()=>{
  const app=setup();
  app.context.diagram={mode:'agent',plan:{...result.plan,dishes:[{id:'gen-a',name:'保留菜'},{id:'reference',name:'参考菜'}]},trace:[
    {kind:'retained',recipe_id:'gen-a'},
    {tool:'find_recipes',result:[{id:'reference'}]},
    {tool:'compose_menu',result:{valid:true,recipe_ids:['gen-a','reference']}},
  ]};
  const html=app.run('renderJourney(diagram)');
  assert.match(html,/保留 1 道菜，从参考菜谱中替换了 1 道菜/);
  assert.doesNotMatch(html,/拟定了/);
});

test('an unrelated retained event cannot reduce the displayed new-dish count',()=>{
  const app=setup();
  app.context.diagram={...agentDiagram,trace:[{kind:'retained',recipe_id:'gen-other'},...agentDiagram.trace]};
  const html=app.run('renderJourney(diagram)');
  assert.match(html,/拟定了 2 道新菜/);
  assert.doesNotMatch(html,/保留 1 道菜/);
});

test('journey cannot turn missing or unrelated evaluation into a successful check',()=>{
  const app=setup();
  app.context.diagram={...agentDiagram,trace:[
    {tool:'evaluate_menu',arguments:['other-a','other-b'],result:{valid:true}},
    {kind:'validation'},
  ]};
  const html=app.run('renderJourney(diagram)');
  assert.match(html,/没有找到这组菜的成功评估记录/);
  assert.match(html,/没有完整的最终核对记录/);
  assert.doesNotMatch(html,/完成最终程序校验/);
});

test('demo illustration explicitly distinguishes local rules from an Agent run',()=>{
  const app=setup();app.context.diagram=result;
  const html=app.run('renderJourney(diagram)');
  assert.match(html,/没有调用大模型，也没有 Agent 运行/);
  assert.doesNotMatch(html,/CodeAgent 实际执行/);
});
