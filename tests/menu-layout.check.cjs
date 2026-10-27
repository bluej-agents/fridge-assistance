// Optional real-browser regression: needs Playwright and a Chromium executable.
// All HTTP responses come from repository files or synthetic menus; no model calls.
const assert = require('node:assert/strict');
const {readFileSync, mkdirSync, writeFileSync} = require('node:fs');
const {resolve} = require('node:path');
const {chromium} = require('playwright');

const root = resolve(__dirname, '..');
const assets = {
  '/': ['text/html', readFileSync(resolve(root, 'fridge/static/index.html'), 'utf8')],
  '/static/style.css': ['text/css', readFileSync(resolve(root, 'fridge/static/style.css'), 'utf8')],
  '/static/app.js': ['application/javascript', readFileSync(resolve(root, 'fridge/static/app.js'), 'utf8')],
};
const ingredient = name => ({name, amount:100, unit:'克', available:true});
const dish = (id, name, names) => ({
  id, name, emoji:'🥬', minutes:14, vegetarian:true, servings:2, ingredients:names.map(ingredient),
  staples:['盐'], steps:['洗净食材。', '充分做熟后装盘。'], source:'排版测试数据',
});
const cases = [
  {name:'extra-ingredient-hint', dishes:[
    dish('left', '蒜苔炒肉丝', ['猪肉','蒜苔','胡萝卜']),
    dish('right', '番茄土豆炖鸡蛋', ['番茄','鸡蛋','土豆','青椒']),
  ]},
  {name:'wrapped-dish-name', dishes:[
    dish('left', '番茄土豆胡萝卜香菇青椒炖五花肉搭配蒜苔和金针菇的家常组合', ['五花肉','蒜苔']),
    dish('right', '番茄炒蛋', ['番茄','鸡蛋','土豆','青椒']),
  ]},
  {name:'wrapped-ingredient-text', dishes:[
    dish('left', '家常蔬菜', ['清洗并切成细丝的胡萝卜和适量新鲜香菇食材说明', '土豆','青椒']),
    dish('right', '清炒白菜', ['白菜']),
  ]},
];
const viewports = [
  {width:1440,height:900}, {width:1366,height:768}, {width:1100,height:800},
  {width:768,height:1024}, {width:390,height:844}, {width:320,height:740},
];
const artifactDir = process.env.LAYOUT_ARTIFACT_DIR;
if (artifactDir) mkdirSync(artifactDir, {recursive:true});

async function main() {
  const launch = {headless:true};
  if (process.env.LAYOUT_BROWSER_EXECUTABLE) launch.executablePath = process.env.LAYOUT_BROWSER_EXECUTABLE;
  const browser = await chromium.launch(launch);
  const report = {browser:browser.version(), cases:[], workflows:[]};
  try {
    const page = await browser.newPage();
    const errors = [];
    page.on('pageerror', error => errors.push(error.message));
    let current, onPlan;
    await page.route('**/*', async route => {
      const path = new URL(route.request().url()).pathname;
      if (assets[path]) {
        const [contentType, body] = assets[path];
        return route.fulfill({contentType, body});
      }
      if (path === '/api/status') return route.fulfill({json:{model_ready:false}});
      if (path === '/api/plan') return onPlan?onPlan(route):route.fulfill({json:current});
      return route.abort();
    });
    for (const viewport of viewports) {
      await page.setViewportSize(viewport);
      for (const scenario of cases) {
        current = {mode:'demo', trace:[], plan:{
          people:2, minutes:28, used:['番茄'], unused:[], shopping:[],
          stock_check:[ingredient('番茄')], staples:['盐'], note:'仅测试布局。', dishes:scenario.dishes,
        }};
        await page.goto('http://127.0.0.1:7860/');
        await page.locator('#submit').click();
        await page.locator('.dish-card').nth(1).waitFor();
        const geometry = await page.locator('.dish-card').evaluateAll(cards => cards.map(card => {
          const rect = element => {
            const r = element.getBoundingClientRect();
            return {top:r.top, bottom:r.bottom, left:r.left, width:r.width, height:r.height};
          };
          return {
            card:rect(card), title:rect(card.querySelector('h3')),
            food:rect(card.querySelector('.food-line')),
            recipe:rect(card.querySelector('.recipe-open')), swap:rect(card.querySelector('.swap')),
            contentFits:[...card.querySelectorAll('h3,.food-line')].every(el => el.scrollHeight <= el.clientHeight + 1),
          };
        }));
        const label = `${viewport.width}px / ${scenario.name}`;
        const [left, right] = geometry;
        if (viewport.width > 580) {
          assert.ok(Math.abs(left.card.top-right.card.top)<1, label+' cards share a row');
          for (const button of ['recipe','swap']) {
            assert.ok(Math.abs(left[button].top-right[button].top)<1, label+' '+button+' top edges align');
            assert.ok(Math.abs(left[button].bottom-right[button].bottom)<1, label+' '+button+' bottom edges align');
          }
        } else {
          assert.ok(right.card.top >= left.card.bottom + 15, label+' cards stack naturally');
        }
        for (const card of geometry) {
          assert.ok(card.contentFits, label+' text remains visible');
          assert.ok(card.recipe.top-card.food.bottom >= 13.5, label+' readable gap above actions');
          assert.ok(card.swap.top >= card.recipe.bottom + 3.5, label+' actions do not overlap');
          assert.ok(card.swap.bottom <= card.card.bottom-15, label+' actions stay inside the card');
          assert.ok(card.recipe.height >= 44 && card.swap.height >= 44, label+' touch targets stay readable');
          assert.ok(card.swap.width < card.recipe.width, label+' swap remains sized to its text');
        }
        assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1), label+' no horizontal overflow');
        if (artifactDir && scenario === cases[0] && [1440,390].includes(viewport.width)) {
          await page.screenshot({path:resolve(artifactDir, `menu-${viewport.width}.png`), fullPage:true});
        }
        await page.locator('[data-recipe-id="right"]').click();
        assert.equal(await page.locator('#recipe-content .recipe-foods li').count(), scenario.dishes[1].ingredients.length);
        await page.keyboard.press('Escape');
        assert.equal(await page.locator('#recipe-dialog').evaluate(el => el.open), false);
        report.cases.push({viewport, name:scenario.name, geometry});
      }
    }
    for (const viewport of [viewports[0], viewports[4]]) {
      await page.setViewportSize(viewport);
      current = {mode:'demo', trace:[], plan:{
        people:2, minutes:28, used:['番茄'], unused:[], shopping:[],
        stock_check:[ingredient('番茄')], staples:['盐'], note:'仅测试交互。',
        dishes:[dish('gen-0000000000000001','番茄炒蛋',['番茄','鸡蛋']), dish('gen-0000000000000002','清炒白菜',['白菜'])],
      }};
      const requests=[];
      let failNext=false, sequence=2;
      onPlan=async route=>{
        const request=route.request().postDataJSON();requests.push(request);
        if(failNext){
          failNext=false;
          return route.fulfill({status:422,json:{detail:'保留另一道菜时没有合适的替代，请调整条件后重试。'}});
        }
        if(request.keep_recipe){
          const kept=current.plan.dishes.find(d=>d.id===request.keep_recipe.id);
          assert.ok(kept,'Request retains a recipe from the currently displayed menu');
          const replacement=dish('gen-'+String(++sequence).padStart(16,'0'),'替换菜'+sequence,['番茄','鸡蛋']);
          current={...current,plan:{...current.plan,dishes:request.keep_index===0?[kept,replacement]:[replacement,kept]}};
        }
        return route.fulfill({json:current});
      };
      await page.goto('http://127.0.0.1:7860/');
      await page.locator('#choose-foods').click();
      await page.locator('.custom-ingredients summary').click();
      await page.locator('#ingredients').fill(['鸡蛋','番茄',...Array.from({length:38},(_,i)=>'自选'+i)].join('、'));
      await page.locator('#ingredient-dialog .primary').click();
      assert.equal(await page.locator('.selected-food').count(),40);
      await page.locator('#submit').click();
      await page.locator('.dish-card').nth(1).waitFor();
      assert.equal(requests[0].ingredients.length,40);
      const snapshot=()=>page.locator('.dish-card').evaluateAll(cards=>cards.map(card=>card.innerHTML));
      for (const replaceIndex of [0,1]) {
        const before=await snapshot(),kept=current.plan.dishes[1-replaceIndex];
        const previousId=current.plan.dishes[replaceIndex].id;
        await page.locator('.swap').nth(replaceIndex).click();
        const newId='gen-'+String(sequence).padStart(16,'0');
        await page.locator(`[data-recipe-id="${newId}"]`).waitFor();
        const request=requests.at(-1),after=await snapshot();
        assert.equal(request.keep_index,1-replaceIndex);
        assert.deepEqual(request.keep_recipe,{
          id:kept.id,name:kept.name,minutes:kept.minutes,vegetarian:kept.vegetarian,
          ingredients:kept.ingredients.map(({name,amount,unit})=>({name,amount,unit})),
          staples:kept.staples,steps:kept.steps,servings:2,
        });
        assert.ok(request.exclude_ids.includes(previousId));
        assert.equal(after[1-replaceIndex],before[1-replaceIndex],'Other card content stays identical');
        assert.notEqual(after[replaceIndex],before[replaceIndex],'Only the clicked card changes');
      }
      report.workflows.push({viewport,name:'left-and-right-single-dish-swaps'});
      const beforeFailure=await snapshot();failNext=true;
      await page.locator('.swap').nth(0).click();
      await page.locator('#error').waitFor({state:'visible'});
      assert.deepEqual(await snapshot(),beforeFailure,'Failed replacement retains both old cards');
      assert.equal(await page.locator('#submit').isEnabled(),true);
      report.workflows.push({viewport,name:'failed-swap-retains-menu'});
      if(viewport.width<=1099)await page.locator('#show-fridge').click();
      const clearBox=await page.locator('#clear-ingredients').boundingBox();
      const tagBox=await page.locator('#selected-ingredients').boundingBox();
      assert.ok(clearBox.y+clearBox.height<=tagBox.y+1,'Clear remains above a long list of tags');
      await page.locator('#clear-ingredients').click();
      assert.equal(await page.locator('.selected-food').count(),0);
      assert.equal(await page.locator('#ingredients').inputValue(),'');
      assert.equal(await page.locator('#clear-ingredients').isDisabled(),true);
      assert.equal(await page.locator('#results').isVisible(),false);
      assert.equal(await page.locator('#error').isVisible(),false);
      await page.locator('#choose-foods').click();
      assert.equal(await page.locator('[data-ingredient]:checked').count(),0);
      assert.ok((await page.locator('[data-select-category]').allTextContents()).every(text=>text==='全选'));
      assert.ok((await page.locator('.category-count').allTextContents()).every(text=>text===''));
      assert.match(await page.locator('#picker-total').textContent(),/已选 0 种/);
      await page.keyboard.press('Escape');
      assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=window.innerWidth+1));
      report.workflows.push({viewport,name:'clear-40-foods-synchronizes-picker'});
    }
    assert.deepEqual(errors, [], 'No page JavaScript errors');
    if (artifactDir) writeFileSync(resolve(artifactDir, 'geometry.json'), JSON.stringify(report, null, 2));
    console.log(`PASS: ${report.cases.length} browser layout cases + ${report.workflows.length} selection/swap workflows; ${report.browser}; aligned actions, visible content, full recipe dialogs.`);
  } finally {
    await browser.close();
  }
}
main().catch(error => { console.error(error); process.exitCode=1; });
