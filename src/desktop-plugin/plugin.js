import {
  ROUTES_AREA, SIDEBAR_NAV_AREA, STATUSBAR_AREAS,
  Button, Badge, StatusDot, Skeleton, ErrorState,
  useQuery, useMutation, useQueryClient, host
} from '@hermes/plugin-sdk'
import { jsx, jsxs } from 'react/jsx-runtime'
import React from 'react'

const ANSI=/\x1b\[[0-?]*[ -/]*[@-~]/g

function out(r){
  if(r==null)return ''
  if(typeof r==='string')return r.replace(ANSI,'')
  for(const k of ['stdout','output','text','result']){
    if(typeof r[k]==='string')return r[k].replace(ANSI,'')
  }
  if(r.data)return out(r.data)
  return ''
}

function exitCode(r){
  if(!r||typeof r!=='object')return 0
  for(const k of ['exit_code','exitCode','code','returncode']){
    if(Number.isFinite(Number(r[k])))return Number(r[k])
  }
  return 0
}

async function sh(command){
  const r=await host.request('shell.exec',{command})
  const text=out(r)
  const code=exitCode(r)
  if(code!==0)throw new Error(text||`Command failed (${code})`)
  return text
}

const ACCOUNT_CMD='__ACCOUNT_CMD__'

function q(s){return `"${String(s).replace(/"/g,'\\"')}"`}
function arg(s){return q(String(s))}
function validName(s){return /^[A-Za-z0-9_-]{1,48}$/.test(String(s||''))}

async function getStatus(refresh=false){
  const suffix=refresh?' --refresh':''
  const text=await sh(`${q(ACCOUNT_CMD)} status${suffix}`)
  try{return JSON.parse(text.trim())}
  catch(e){throw new Error(`ACP status returned invalid JSON: ${text.slice(0,500)}`)}
}

async function getAccounts(){
  const text=await sh(`${q(ACCOUNT_CMD)} list`)
  try{return JSON.parse(text.trim())}
  catch(e){throw new Error(`Account helper returned invalid JSON: ${text.slice(0,500)}`)}
}

async function switchAccount(name){return sh(`${q(ACCOUNT_CMD)} switch ${arg(name)}`)}
async function useOriginal(){return sh(`${q(ACCOUNT_CMD)} original`)}
async function deleteAccount(name){return sh(`${q(ACCOUNT_CMD)} delete ${arg(name)}`)}

async function launchAuth(name){
  if(!validName(name)){
    throw new Error("Profile name may contain only letters, digits, '-' or '_' and must be 48 characters or fewer.")
  }
  return sh(`start "" cmd.exe /k call ${q(ACCOUNT_CMD)} auth ${arg(name)}`)
}

function fmtDate(s){
  if(!s)return 'Not verified'
  try{return new Date(s).toLocaleString()}
  catch{return String(s)}
}

function Notice({notice}){
  if(!notice)return null
  const title=notice.kind==='success'?'Success':notice.kind==='error'?'Error':'Info'
  return jsxs('div',{
    className:'rounded-md border border-(--ui-stroke-secondary) px-3 py-2 text-sm',
    children:[
      jsx('div',{className:'font-medium',children:title}),
      jsx('div',{className:'mt-1 text-(--ui-text-secondary)',children:notice.text})
    ]
  })
}

function Stat({label,value,online}){
  return jsxs('div',{
    className:'min-w-0 rounded-md border border-(--ui-stroke-secondary) px-3 py-2',
    children:[
      jsx('div',{className:'text-xs text-(--ui-text-tertiary)',children:label}),
      jsxs('div',{className:'mt-1 flex min-w-0 items-center gap-2',children:[
        online!==undefined?jsx(StatusDot,{status:online?'online':'offline'}):null,
        jsx('div',{className:'truncate text-sm font-medium',children:value})
      ]})
    ]
  })
}

function AccountRow({name,active,subtitle,onUse,onRemove,busy,original}){
  return jsxs('div',{
    className:'flex items-center justify-between gap-3 border-b border-(--ui-stroke-secondary) py-2.5 last:border-0',
    children:[
      jsxs('div',{className:'min-w-0',children:[
        jsxs('div',{className:'flex min-w-0 items-center gap-2',children:[
          jsx(StatusDot,{status:active?'online':'offline'}),
          jsx('span',{className:'truncate text-sm font-medium',children:name}),
          active?jsx(Badge,{children:'Active'}):null
        ]}),
        subtitle?jsx('div',{className:'mt-0.5 truncate text-xs text-(--ui-text-tertiary)',children:subtitle}):null
      ]}),
      jsxs('div',{className:'flex shrink-0 items-center gap-2',children:[
        jsx(Button,{
          variant:'secondary',
          disabled:active||busy,
          onClick:onUse,
          children:active?'In use':'Use'
        }),
        !original?jsx(Button,{
          variant:'ghost',
          disabled:active||busy,
          onClick:onRemove,
          children:'Remove'
        }):null
      ]})
    ]
  })
}

function ModelPicker({models}){
  const first=(models&&models[0]&&models[0].id)||''
  const [selected,setSelected]=React.useState(first)

  React.useEffect(()=>{
    if(!selected&&first)setSelected(first)
    if(selected&&!models.some(m=>m.id===selected))setSelected(first)
  },[first,models,selected])

  const current=models.find(m=>m.id===selected)||null

  return jsxs('section',{
    className:'rounded-md border border-(--ui-stroke-secondary) p-4',
    children:[
      jsxs('div',{className:'flex flex-wrap items-center justify-between gap-3',children:[
        jsxs('div',{children:[
          jsx('div',{className:'text-sm font-medium',children:'Available models'}),
          jsx('div',{
            className:'mt-1 text-xs text-(--ui-text-tertiary)',
            children:'This list is informational. Select the active inference model from Hermes model settings.'
          })
        ]}),
        jsx(Badge,{children:`${models.length} models`})
      ]}),
      models.length?jsxs('div',{className:'mt-3 grid gap-3 md:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]',children:[
        jsx('select',{
          value:selected,
          onChange:e=>setSelected(e.target.value),
          className:'w-full rounded-md border border-(--ui-stroke-secondary) bg-(--ui-bg-primary) px-3 py-2 text-sm',
          children:models.map(m=>jsx('option',{value:m.id,children:m.name||m.id},m.id))
        }),
        jsxs('div',{className:'min-w-0 rounded-md border border-(--ui-stroke-secondary) px-3 py-2',children:[
          jsx('div',{className:'truncate text-sm font-medium',children:current?(current.name||current.id):'No model selected'}),
          jsx('div',{className:'mt-0.5 truncate text-xs text-(--ui-text-tertiary)',children:current?current.id:''})
        ]})
      ]}):jsx('div',{className:'mt-3 text-sm text-(--ui-text-tertiary)',children:'No models returned by the official ACP runtime.'})
    ]
  })
}

function Page(){
  const qc=useQueryClient()
  const [name,setName]=React.useState('')
  const [notice,setNotice]=React.useState(null)

  const status=useQuery({
    queryKey:['ag452','status'],
    queryFn:()=>getStatus(false),
    refetchOnWindowFocus:false,
    retry:1
  })

  const accounts=useQuery({
    queryKey:['ag452','accounts'],
    queryFn:getAccounts,
    refetchOnWindowFocus:false,
    retry:0
  })

  const refresh=async()=>{
    setNotice({kind:'info',text:'Refreshing ACP account and model information.'})
    try{
      const [sd,ad]=await Promise.all([getStatus(true),getAccounts()])
      qc.setQueryData(['ag452','status'],sd)
      qc.setQueryData(['ag452','accounts'],ad)
      const active=ad.active||'Original Hermes login'
      setNotice({
        kind:'success',
        text:`Refresh complete. Active account: ${active}. Saved accounts: ${(ad.profiles||[]).length}. Models: ${(sd.models||[]).length}.`
      })
    }catch(e){
      setNotice({kind:'error',text:String(e)})
    }
  }

  const add=useMutation({
    mutationFn:launchAuth,
    onMutate:()=>setNotice({kind:'info',text:'Opening the Google sign-in window.'}),
    onSuccess:(_,n)=>{
      setName('')
      setNotice({
        kind:'success',
        text:`Sign-in started for "${n}". Finish Google OAuth. When the terminal shows AUTH_OK, return here and click Refresh.`
      })
    },
    onError:e=>setNotice({kind:'error',text:'Could not start account sign-in: '+String(e)})
  })

  const sw=useMutation({
    mutationFn:switchAccount,
    onSuccess:async(_,n)=>{
      setNotice({kind:'success',text:`Switching to "${n}". Hermes gateway will restart.`})
      host.notify({kind:'success',message:`Antigravity account switched to ${n}`})
      await accounts.refetch()
      host.restartGateway()
    },
    onError:e=>setNotice({kind:'error',text:'Switch failed: '+String(e)})
  })

  const original=useMutation({
    mutationFn:useOriginal,
    onSuccess:async()=>{
      setNotice({kind:'success',text:'Restoring the original Hermes Antigravity login. Hermes gateway will restart.'})
      await accounts.refetch()
      host.restartGateway()
    },
    onError:e=>setNotice({kind:'error',text:'Could not restore original login: '+String(e)})
  })

  const del=useMutation({
    mutationFn:deleteAccount,
    onSuccess:async(_,n)=>{
      setNotice({kind:'success',text:`Removed saved account "${n}".`})
      await accounts.refetch()
    },
    onError:e=>setNotice({kind:'error',text:'Remove failed: '+String(e)})
  })

  if(status.isLoading||accounts.isLoading){
    return jsx('div',{className:'p-5',children:jsx(Skeleton,{className:'h-48 w-full'})})
  }

  if(status.error){
    return jsx('div',{className:'p-5',children:jsx(ErrorState,{
      title:'Antigravity unavailable',
      description:String(status.error)
    })})
  }

  if(accounts.error){
    return jsx('div',{className:'p-5',children:jsx(ErrorState,{
      title:'Account manager unavailable',
      description:String(accounts.error)
    })})
  }

  const d=status.data||{}
  const ad=accounts.data||{}
  const list=ad.profiles||[]
  const active=ad.active||null
  const models=d.models||[]
  const busy=sw.isPending||original.isPending||del.isPending

  return jsxs('div',{
    className:'mx-auto flex w-full max-w-3xl flex-col gap-4 p-5',
    children:[
      jsxs('div',{className:'flex flex-wrap items-start justify-between gap-3',children:[
        jsxs('div',{children:[
          jsx('h1',{className:'text-lg font-semibold',children:'Google Antigravity'}),
          jsx('div',{
            className:'mt-1 text-xs text-(--ui-text-tertiary)',
            children:'Official Google Antigravity ACP provider and account manager'
          })
        ]}),
        jsx(Button,{variant:'ghost',onClick:refresh,children:'Refresh'})
      ]}),

      jsx(Notice,{notice}),

      jsxs('div',{className:'grid grid-cols-1 gap-2 sm:grid-cols-3',children:[
        jsx(Stat,{label:'Connection',value:d.connected?'Connected':'Disconnected',online:!!d.connected}),
        jsx(Stat,{label:'Active account',value:active||'Original Hermes login'}),
        jsx(Stat,{label:'ACP version',value:d.version||'Unknown'})
      ]}),

      jsxs('section',{className:'rounded-md border border-(--ui-stroke-secondary) p-4',children:[
        jsxs('div',{className:'mb-2 flex flex-wrap items-center justify-between gap-2',children:[
          jsxs('div',{children:[
            jsx('div',{className:'text-sm font-medium',children:'Accounts'}),
            jsx('div',{
              className:'mt-1 text-xs text-(--ui-text-tertiary)',
              children:'Each saved account uses its own isolated Google ACP sign-in state.'
            })
          ]}),
          jsx(Badge,{children:`${list.length} saved`})
        ]}),

        jsx(AccountRow,{
          name:'Original Hermes login',
          active:!active,
          subtitle:'Default isolated Hermes Antigravity sign-in',
          onUse:()=>original.mutate(),
          busy,
          original:true
        }),

        ...list.map(a=>jsx(AccountRow,{
          name:a.name,
          active:!!a.active,
          subtitle:`Verified: ${fmtDate(a.verifiedAt)}${Number.isFinite(a.modelsSeen)?` | ${a.modelsSeen} models`:''}`,
          onUse:()=>sw.mutate(a.name),
          onRemove:()=>del.mutate(a.name),
          busy,
          original:false
        },a.name)),

        list.length===0?jsx('div',{
          className:'py-2 text-xs text-(--ui-text-tertiary)',
          children:'No additional accounts have been saved.'
        }):null,

        jsxs('div',{className:'mt-3 border-t border-(--ui-stroke-secondary) pt-3',children:[
          jsx('div',{className:'mb-2 text-sm font-medium',children:'Add account'}),
          jsxs('div',{className:'flex flex-wrap items-center gap-2',children:[
            jsx('input',{
              value:name,
              onChange:e=>setName(e.target.value),
              placeholder:'Profile name',
              className:'min-w-56 flex-1 rounded-md border border-(--ui-stroke-secondary) bg-transparent px-3 py-2 text-sm'
            }),
            jsx(Button,{
              disabled:!validName(name)||add.isPending,
              onClick:()=>add.mutate(name),
              children:add.isPending?'Opening':'Sign in'
            })
          ]}),
          jsx('div',{
            className:'mt-2 text-xs text-(--ui-text-tertiary)',
            children:'Complete Google OAuth in the opened terminal/browser. After AUTH_OK, return here and click Refresh.'
          })
        ]})
      ]}),

      jsx(ModelPicker,{models}),

      jsx('div',{
        className:'text-xs text-(--ui-text-tertiary)',
        children:'Hermes Antigravity ACP 4.6.0 | Manual account switching | No background polling | Hermes core unchanged'
      })
    ]
  })
}

export default{
  id:'antigravity-manager',
  name:'Google Antigravity',
  defaultEnabled:true,
  register(ctx){
    ctx.registerMany([
      {id:'page',area:ROUTES_AREA,data:{path:'/antigravity'},render:()=>jsx(Page,{})},
      {id:'nav',area:SIDEBAR_NAV_AREA,order:80,data:{path:'/antigravity',label:'Antigravity',codicon:'sparkle'}},
      {id:'status',area:STATUSBAR_AREAS.right,order:125,data:{
        id:'antigravity',
        label:'Antigravity',
        icon:'sparkle',
        onSelect:()=>host.navigate('/antigravity')
      }}
    ])
  }
}
