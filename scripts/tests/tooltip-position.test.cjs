const {test}=require('node:test')
const assert=require('node:assert/strict')
const fs=require('node:fs'),ts=require('typescript')
const source=fs.readFileSync('app/src/components/shared/tooltipPosition.ts','utf8')
const mod={exports:{}}
new Function('exports','module',ts.transpileModule(source,{compilerOptions:{module:ts.ModuleKind.CommonJS}}).outputText)(mod.exports,mod)
const {tooltipPosition}=mod.exports
const rect=(left,top,width=60,height=20)=>({left,top,width,height,right:left+width,bottom:top+height})
test('screen anchor stays centered with exactly the requested gap at all zooms',()=>{
 for(const scale of [.585,.63,.9,1,1.26]){
  const anchor=rect(480*scale,230*scale,68*scale,25*scale)
  const p=tooltipPosition(anchor,80*scale,28*scale,1600,1000,14*scale)
  assert.ok(Math.abs(p.left+40*scale-(anchor.left+anchor.width/2))<.00001)
  assert.ok(Math.abs(anchor.top-p.top-28*scale-14*scale)<.00001)
 }
})
test('edge collisions clamp the popup and keep its arrow pointing to the trigger',()=>{
 const a=rect(3,100)
 const p=tooltipPosition(a,120,28,500,300,10)
 assert.equal(p.left,10)
 assert.equal(p.arrow,a.left+a.width/2-p.left)
 const r=tooltipPosition(rect(440,100),100,28,500,300,10)
 assert.equal(r.left,390)
})
test('insufficient space above flips below without scaling coordinates again',()=>{
 const p=tooltipPosition(rect(200,5),80,30,500,300,12)
 assert.equal(p.side,'bottom')
 assert.equal(p.top,37)
})
test('side placement and alignment respect the same viewport coordinates',()=>{
 const a=rect(200,100)
 assert.deepEqual(tooltipPosition(a,80,30,600,400,10,'right','start'),{left:270,top:100,side:'right',arrow:10})
 assert.equal(tooltipPosition(rect(580,100),80,30,600,400,10,'right').side,'left')
})
