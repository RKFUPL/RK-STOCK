const fallbackCodes:Record<string,string>={inaara:'INA',hastakala:'HAS',aakar:'AAK',aakaar:'AAK',anamika:'ANA',naqab:'NAQ',sandook:'SAN'};
const part=(value:string)=>value.trim().toUpperCase().replace(/[^A-Z0-9]+/g,'-').replace(/^-|-$/g,'');
export function collectionCode(name:string,configured?:string){return configured||fallbackCodes[name.toLowerCase()]||part(name).replaceAll('-','').slice(0,3)}
export function linesheetSku(collection:string,productCode:string,color:string,setOf:number,configuredCode?:string){if(!collection||!productCode||!color)return '';return `RK-${collectionCode(collection,configuredCode)}-${part(productCode)}-${part(color)}-${setOf}`}
