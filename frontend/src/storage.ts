import type {Conversation, Identity} from './types.ts';
export function decodeIdentity(token:string):Identity {
  const parts=token.trim().split('.');
  if(parts.length!==3) throw Error('请输入完整 JWT。');
  const value=JSON.parse(new TextDecoder().decode(Uint8Array.from(atob(parts[1].replace(/-/g,'+').replace(/_/g,'/')),c=>c.charCodeAt(0))));
  const uuid=/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
  if(!uuid.test(value.tenant_id)||!uuid.test(value.sub)||!Array.isArray(value.roles)||!value.roles.every((r:unknown)=>typeof r==='string')||typeof value.exp!=='number') throw Error('JWT 身份字段不完整。');
  if(value.exp*1000<=Date.now()) throw Error('JWT 已过期，请生成新的令牌。');
  return value;
}
export function storageKey(identity:Identity){return `shopping-qna:v1:${identity.tenant_id}:${identity.sub}`;}
export function readConversations(raw:string|null):Conversation[]{
  try {const data=JSON.parse(raw||'null');return data?.version===1&&Array.isArray(data.conversations)?data.conversations.filter((c:Conversation)=>c.version===1&&typeof c.threadId==='string'&&typeof c.title==='string'&&Array.isArray(c.messages)&&c.messages.every(m=>typeof m.id==='string'&&typeof m.text==='string'&&['user','assistant'].includes(m.role))):[];}catch{return [];}
}
export function newConversation():Conversation {const date=new Date().toISOString();return {version:1,threadId:crypto.randomUUID(),title:'新的造型灵感',createdAt:date,updatedAt:date,messages:[],state:null};}
export function serializeConversations(conversations:Conversation[]){
  const publicFields=['verdict','summary','strengths','issues','changes','suggestions','clarification_question'];
  return JSON.stringify({version:1,conversations:conversations.map(c=>({...c,messages:c.messages.map(m=>({id:m.id,role:m.role,text:m.text,imageKeys:m.imageKeys,response:m.response?{thread_id:m.response.thread_id,run_id:m.response.run_id,intent:m.response.intent,status:m.response.status,message:m.response.message,conversation_state:m.response.conversation_state,display_items:m.response.display_items?.map(i=>({item_id:i.item_id,object_key:i.object_key,category:i.category,sub_category:i.sub_category,colors:i.colors,style:i.style})),result:m.response.result?Object.fromEntries(Object.entries(m.response.result).filter(([key])=>publicFields.includes(key))):null}:undefined}))}))});
}
