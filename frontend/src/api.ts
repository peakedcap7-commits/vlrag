export class ApiError extends Error {status:number; constructor(message:string,status:number){super(message);this.status=status;}}
export async function request<T>(path:string,token:string,body?:unknown,signal?:AbortSignal):Promise<T>{
  const form=body instanceof FormData;
  const timeout=AbortSignal.timeout(300_000);
  const response=await fetch(`/api${path}`,{method:body===undefined?'GET':'POST',headers:{Authorization:`Bearer ${token}`,...(body===undefined||form?{}:{'Content-Type':'application/json'})},body:body===undefined?undefined:form?body:JSON.stringify(body),signal:signal?AbortSignal.any([signal,timeout]):timeout});
  if(response.status===401) window.dispatchEvent(new Event('auth-expired'));
  if(!response.ok){let message=`请求失败（${response.status}）`;try{const data=await response.json();if(typeof data.detail==='string')message=data.detail;}catch{}throw new ApiError(message,response.status);}
  return response.status===204?undefined as T:response.json();
}
export async function imageBlob(key:string,token:string,signal:AbortSignal):Promise<Blob>{
  for(let attempt=0;attempt<2;attempt++){
    const data=await request<{items:{key:string;content_url:string}[]}>('/assets/urls',token,{keys:[key]},signal);
    const url=data.items.find(i=>i.key===key)?.content_url;
    if(!url?.startsWith('/api/assets/content/'))throw Error('图片暂不可用');
    const response=await fetch(url,{headers:{Authorization:`Bearer ${token}`},signal});
    if(response.status===401){window.dispatchEvent(new Event('auth-expired'));throw Error('身份已失效');}
    if(response.ok)return response.blob();
    if(attempt===1||![403,404,410].includes(response.status))throw Error('图片已过期或不可用');
  }
  throw Error('图片暂不可用');
}
