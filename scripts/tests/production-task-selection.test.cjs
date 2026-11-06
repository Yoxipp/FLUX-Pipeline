const { test } = require('node:test')
const assert = require('node:assert/strict')
const fs = require('node:fs')
const path = require('node:path')
const ts = require('typescript')
const cache = {}
function load(name) {
  if (cache[name]) return cache[name]
  const source = fs.readFileSync(path.join(__dirname, '../../app/src/pages/Production', name + '.ts'), 'utf8')
  const compiled = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020 } }).outputText
  const mod = { exports: {} }
  cache[name] = mod.exports
  new Function('exports', 'require', 'module', compiled)(mod.exports, n => n.startsWith('./') ? load(n.slice(2)) : require(n), mod)
  return mod.exports
}

const m = load('taskSelection')
const task = name => ({ id: name, name, order: 0, type_tokens: [name], known_subtasks: [] })
const fixture = () => ({version: 1, sequences: [{id:'seq',name:'SEQ0010',order:0,tasks:[task('ANIM'),task('LIGHT')],assets:[]}], assets:[{id:'asset',name:'HERO',class:'CHAR',order:0,group_id:null,tasks:[task('ANIM')],assets:[],task_details:{ANIM:{notes:'Asset',status:'WIP'}}}], asset_groups:[], shots: [0,1,2].map(n=>({id:'sh'+n,name:'SHOT'+n,seq_id:'seq',order:n,inherit_tasks:true,tasks:[],assets:[],task_details:{ANIM:{status:'WIP',notes:'Keep',assignee:'OLD'},LIGHT:{status:'TODO'}}}))})
const targets = s => s.shots.flatMap(entity=>['ANIM','LIGHT'].map(departmentId=>({entity,task:task(departmentId),departmentId,statuses:['TODO','WIP','APPROVED']})))
const key = (s,row,col) => m.taskSelectionKey(targets(s)[row*2+col])

test('Ctrl toggles individual tasks, with stable logical keys after task materialization',()=>{
 const s=fixture(), t=targets(s)
 let selection=m.selectProductionTask(m.emptyTaskSelection(),t,key(s,0,0),true,false)
 selection=m.selectProductionTask(selection,t,key(s,2,1),true,false)
 assert.deepEqual(selection.keys,[key(s,0,0),key(s,2,1)])
 selection=m.selectProductionTask(selection,t,key(s,0,0),true,false)
 assert.deepEqual(selection.keys,[key(s,2,1)])
 assert.equal(m.taskSelectionKey({...t[0],task:{...t[0].task,id:'materialized'}}),key(s,0,0))
})
test('Shift selects the same department across rows; diagonal range selects a rectangle',()=>{
 const s=fixture(), t=targets(s)
 const start=m.selectProductionTask(m.emptyTaskSelection(),t,key(s,0,0),false,false)
 assert.deepEqual(m.selectProductionTask(start,t,key(s,2,0),false,true).keys,[key(s,0,0),key(s,1,0),key(s,2,0)])
 assert.deepEqual(m.selectProductionTask(start,t,key(s,1,1),false,true).keys,t.slice(0,4).map(m.taskSelectionKey))
 const reverse=m.selectProductionTask(m.emptyTaskSelection(),t,key(s,2,1),false,false)
 assert.equal(m.selectProductionTask(reverse,t,key(s,0,0),false,true).keys.length,6)
})
test('Ctrl+Shift extends selection, and filtered/collapsed tasks lose selection and anchor',()=>{
 const s=fixture(), t=targets(s)
 let selection=m.selectProductionTask(m.emptyTaskSelection(),t,key(s,2,1),false,false)
 selection=m.selectProductionTask(selection,t,key(s,0,0),true,false)
 selection=m.selectProductionTask(selection,t,key(s,1,0),true,true)
 assert.deepEqual(selection.keys,[key(s,2,1),key(s,0,0),key(s,1,0)])
 const visible=[key(s,2,1)]
 assert.deepEqual(m.pruneTaskSelection(selection,visible),{keys:visible,anchor:null})
 assert.equal(m.pruneTaskSelection(selection,t.map(m.taskSelectionKey)),selection)
 assert.deepEqual(m.selectProductionTask(selection,t.slice(2),key(s,1,1),false,true),{keys:[key(s,1,1)],anchor:key(s,1,1)})
})
test('batch assignment preserves review fields and templates, including locked shots and assets',()=>{
 const s=fixture(); s.shots[1].locked={by:'ME',at:'now'}
 const t=[...targets(s).filter(x=>x.task.name==='ANIM'),{entity:s.assets[0],task:task('ANIM')}]
 const original=JSON.stringify(s), next=m.applyTaskSelection(s,t,{kind:'artist',value:'TOM'})
 assert.equal(next.shots[0].task_details.ANIM.notes,'Keep')
 assert.equal(next.shots[0].task_details.ANIM.status,'WIP')
 assert.equal(next.assets[0].task_details.ANIM.assignee,'TOM')
 assert.equal(next.shots[1].tasks.length,0)
 assert.equal(next.shots[1].task_details.ANIM.assignee,'TOM')
 assert.equal(next.sequences[0].task_details,undefined)
 assert.equal(JSON.stringify(s),original)
 const removed=m.applyTaskSelection(next,t,{kind:'artist',value:''})
 assert.equal(removed.shots[2].task_details.ANIM.assignee,'')
})
test('batch status respects department options and clearing badges retains notes and artists',()=>{
 const s=fixture(), t=targets(s)
 t[1].statuses=['TODO']
 const next=m.applyTaskSelection(s,t,{kind:'status',value:'APPROVED'})
 assert.equal(next.shots[0].task_details.LIGHT.status,'TODO')
 assert.equal(next.shots[2].task_details.ANIM.status,'APPROVED')
 const cleared=m.applyTaskSelection(next,t,{kind:'clear'})
 assert.equal(cleared.shots[0].task_details.ANIM.status,'')
 assert.equal(cleared.shots[0].task_details.ANIM.notes,'Keep')
 assert.equal(cleared.shots[0].task_details.ANIM.assignee,'OLD')
})
test('optional empty cells are selectable and missing entities are never resurrected',()=>{
 const s=fixture(), dep={id:'fx',name:'FX',task_tokens:['FX'],fixed:false,statuses:['TODO'],depends_on:[],scope:'shot',active:true}
 const tasks=m.trackingCellTasks(s,s.shots[0],dep,false,'ME')
 assert.equal(tasks[0].name,'FX')
 assert.equal(m.trackingCellTasks(s,s.shots[0],dep,true,'ME').length,0)
 const next=m.applyTaskSelection(s,[{entity:s.shots[0],task:tasks[0]}],{kind:'status',value:'TODO'})
 assert.equal(next.shots[0].task_details.FX.status,'TODO')
 const missing={...s,shots:[]}
 assert.equal(m.applyTaskSelection(missing,targets(s),{kind:'artist',value:'TOM'}),missing)
})

test('Mine gaps preserve physical department order for Shift rectangles',()=>{
 const s=fixture()
 const t=[{entity:s.shots[0],task:task('FX'),departmentId:'FX',columnOrder:2},
 {entity:s.shots[1],task:task('ANIM'),departmentId:'ANIM',columnOrder:0},
 {entity:s.shots[1],task:task('LIGHT'),departmentId:'LIGHT',columnOrder:1},
 {entity:s.shots[2],task:task('LIGHT'),departmentId:'LIGHT',columnOrder:1}]
 const start=m.selectProductionTask(m.emptyTaskSelection(),t,m.taskSelectionKey(t[0]),false,false)
 assert.deepEqual(m.selectProductionTask(start,t,m.taskSelectionKey(t[3]),false,true).keys,[t[0],t[2],t[3]].map(m.taskSelectionKey))
})
