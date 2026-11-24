/** Serialize preview generation so a slow response never replaces newer edits. */
export function createPreviewQueue({request,apply,fail,loading,delay=350}) {
  let pending=null, running=false, timer=null, version=0, disposed=false
  async function flush() {
    clearTimeout(timer)
    if(running||disposed)return
    running=true
    loading(true)
    try {
      while(pending&&!disposed) {
        const task=pending
        pending=null
        try {
          const result=await request(task.data)
          if(task.version===version&&!disposed)apply(result)
        } catch(error) {
          if(task.version===version&&!disposed)fail(error)
        }
      }
    } finally {
      running=false
      loading(false)
    }
  }
  return {
    schedule(data,immediate=false) {
      if(disposed)return
      pending={data:JSON.parse(JSON.stringify(data)),version:++version}
      clearTimeout(timer)
      if(immediate)void flush()
      else timer=setTimeout(flush,delay)
    },
    cancel(){version++;pending=null;clearTimeout(timer)},
    dispose(){this.cancel();disposed=true}
  }
}
