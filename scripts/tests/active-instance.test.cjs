const {test}=require('node:test')
const assert=require('node:assert/strict')
const fs=require('node:fs'),ts=require('typescript')
const source=fs.readFileSync('app/src/lib/activeInstance.ts','utf8')
const mod={exports:{}}
new Function('exports','module',ts.transpileModule(source,{compilerOptions:{module:ts.ModuleKind.CommonJS}}).outputText)(mod.exports,mod)
const {reconcileChoices,targetPort}=mod.exports
const a={port:48884,pid:10},b={port:48885,pid:20}
const st=(...insts)=>({Houdini:{instances:insts}})

test('a single instance connects alone',()=>{
 const r=reconcileChoices({},st(a),{})
 assert.deepEqual(r.choices.Houdini,{port:48884,pid:10})
 assert.equal(r.lost.length,0)
})
test('several instances without a choice: FLUX never guesses',()=>{
 const r=reconcileChoices({},st(a,b),{})
 assert.equal(r.choices.Houdini,undefined)
 assert.equal(targetPort('Houdini',r.choices,[a,b],{}),null)
})
test('a new instance does not steal the choice',()=>{
 const r=reconcileChoices({Houdini:{port:48884,pid:10}},st(a,b),{})
 assert.equal(r.changed,false)
 assert.equal(targetPort('Houdini',r.choices,[a,b],{}),48884)
})
test('the chosen one closed, one left: FLUX moves to it and says so',()=>{
 const r=reconcileChoices({Houdini:{port:48884,pid:10}},st(b),{})
 assert.deepEqual(r.choices.Houdini,{port:48885,pid:20})
 assert.equal(r.lost[0].taken.port,48885)
})
test('port taken back by another process counts as closed, several left: no choice',()=>{
 const other={port:48884,pid:99}
 const r=reconcileChoices({Houdini:{port:48884,pid:10}},st(other,b),{})
 assert.equal(r.choices.Houdini,undefined)
 assert.equal(r.lost[0].taken,null)
 assert.equal(r.lost[0].remaining,2)
})
test('a lost choice stays lost on the next status tick (no silent first instance)',()=>{
 const first=reconcileChoices({Houdini:{port:48884,pid:10}},st({port:48884,pid:99},b),{})
 const second=reconcileChoices(first.choices,st({port:48884,pid:99},b),first.disconnected)
 assert.equal(second.choices.Houdini,undefined)
 assert.equal(second.lost.length,0)
})
test('the pid of an old choice is learned',()=>{
 const r=reconcileChoices({Houdini:{port:48884,pid:null}},st(a,b),{})
 assert.deepEqual(r.choices.Houdini,{port:48884,pid:10})
 assert.equal(r.changed,true)
})
test('a disconnected DCC is not taken back, until all its instances closed',()=>{
 const off={Houdini:true}
 const r=reconcileChoices({},st(a),off)
 assert.equal(r.choices.Houdini,undefined)
 assert.equal(targetPort('Houdini',r.choices,[a],off),null)
 const closed=reconcileChoices({},st(),off)
 assert.equal(closed.disconnected.Houdini,undefined)
 assert.equal(reconcileChoices({},st(a),closed.disconnected).choices.Houdini.port,48884)
})
test('no instance: the stored choice waits, nothing is targeted',()=>{
 const r=reconcileChoices({Houdini:{port:48884,pid:10}},st(),{})
 assert.equal(r.choices.Houdini.port,48884)
 assert.equal(targetPort('Houdini',r.choices,[],{}),null)
})
