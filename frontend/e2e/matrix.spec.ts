import {test, expect} from "@playwright/test";
for (const width of [1280,390,320]) test(`single matrix confirms groups and resumes approval at ${width}px`, async ({page},info) => {
  await page.setViewportSize({width,height:900}); let draft: Record<string,unknown> | null=null; let status="AWAITING_APPROVAL"; let approvals=0;
  await page.route("**/api/v1/**",async route=>{
    const request=route.request(),path=new URL(request.url()).pathname;
    if(path.endsWith("/bootstrap"))return route.fulfill({json:{csrf_token:"fixture"}});
    if(path.endsWith("/projects"))return route.fulfill({json:{items:[{id:"p",title:"研究",archived:false}]}});
    if(path.endsWith("/model-profiles"))return route.fulfill({json:{items:[{id:"m",label:"Mock",provider:"ollama"}]}});
    if(path.endsWith("/conversations"))return route.fulfill({json:{items:[{id:"c",project_id:"p",title:"矩阵聊天",selected_profile_id:"m"}]}});
    if(path.endsWith("/messages"))return route.fulfill({json:{items:[]}});
    if(path.endsWith("/events"))return route.fulfill({contentType:"text/event-stream",body:""});
    if(path.endsWith("/matrices")){if(request.method()==="POST")draft={id:"x",revision:1,status:"DRAFT",sha256:"synthetic",headers:["gene","A","B","C","D"],row_count:1,preview:[["g1","10","20","30","40"]]};return route.fulfill({json:draft});}
    if(path.endsWith("/x/confirm")){const body=request.postDataJSON();expect(body.groups).toEqual({"1":"Control","2":"Control","3":"AD","4":"AD"});expect(body.goal).toBe("比较处理相对对照"); draft={...draft,status:"CONFIRMED",dataset_id:"d",turn_id:"t",run_id:"r"};return route.fulfill({json:draft});}
    if(path.endsWith("/turns/t"))return route.fulfill({json:{id:"t",status:"WAITING_USER",run_id:"r",input_revision:1,pending_input:null}});
    if(path.endsWith("/runs/r"))return route.fulfill({json:{status}});
    if(path.endsWith("/r/artifacts")) return route.fulfill({json:{run_id:"r",artifacts:[{artifact_id:"csv",name:"all_results.csv",sha256:"fixture",media_type:"text/csv"}]}});
    if(path.endsWith("/r/artifacts/csv")) return route.fulfill({contentType:"text/csv",body:"feature_id,log2FoldChange,padj\nGENE_1,2,0.01"});
    if(path.endsWith("/r/plan"))return route.fulfill({json:{run_id:"r",plan_revision:1,plan:{comparison:{factor:"condition",numerator:"AD",denominator:"Control"}}}});
    if(path.endsWith("/r/approval")){approvals++;status="RUNNING";return route.fulfill({json:{status}});}
    if(path.endsWith("/r/cancel")){status="CANCELLED";return route.fulfill({json:{status}});}
    return route.fulfill({json:{items:[]}});
  });
  await page.goto("/");if(width<900)await page.getByRole("button",{name:"项目与对话"}).click();await page.getByRole("button",{name:"矩阵聊天",exact:true}).click();
  await page.getByRole("button",{name:"添加",exact:true}).click();await page.getByRole("button",{name:"上传单表达矩阵"}).click();await page.getByLabel("单表达矩阵文件").setInputFiles({name:"matrix.csv",mimeType:"text/csv",buffer:Buffer.from("gene,A,B,C,D\ng1,10,20,30,40")});
  for(const name of ["A","B","C","D"])await page.getByLabel(`分组 ${name}`,{exact:true}).fill(["A","B"].includes(name)?"Control":"AD");
  await page.getByLabel("实验组",{exact:true}).fill("AD");await page.getByLabel("对照组",{exact:true}).fill("Control");await page.getByLabel("数据类型",{exact:true}).selectOption("RAW_COUNTS");await page.getByLabel("矩阵来源").fill("合成原始counts，未经归一化");await page.getByLabel("矩阵研究目标").fill("比较处理相对对照");await page.getByRole("button",{name:"确认分组并生成待审批方案"}).click();
  await expect(page.getByRole("button",{name:"批准分析"})).toBeDisabled();expect(approvals).toBe(0);await page.reload();await page.getByRole("button",{name:"恢复此分析"}).click();await page.getByLabel("我已核对本次方案").check();await page.getByRole("button",{name:"批准分析"}).click();await expect(page.getByText("运行状态：RUNNING")).toBeVisible();if(width===1280){status="COMPLETED";await page.getByRole("button",{name:"打开 all_results.csv"}).click();await expect(page.getByRole("cell",{name:"GENE_1"})).toBeVisible();}else{await page.getByRole("button",{name:"停止运行"}).click();await expect(page.getByText("运行状态：CANCELLED")).toBeVisible();}expect(approvals).toBe(1);expect(await page.evaluate(()=>document.documentElement.scrollWidth)).toBeLessThanOrEqual(width);await page.screenshot({path:info.outputPath(`matrix-${width}.png`)});
});
