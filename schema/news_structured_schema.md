# 勞工新聞文本結構化特徵 Schema

用於對 `data/news_dataset/raw` 中的勞工新聞文本進行按篇結構化抽取，以支援後續 RAG 檢索與摘要生成。


## JSON Schema

```json
{
  "metadata": {
    "title": "",           // string（不可為空）：新聞標題
    "author": "",          // string（不可為空）：作者或機構
    "date": "",            // string（不可為空，YYYY-MM-DD）：發布日期
    "source": "",          // string（不可為空）：新聞來源網址
    "identifier": ""       // string（不可為空）：唯一標識符
  },

  "5W1H": {
    "who": "",             // string（不可為空）：涉及的勞動者、用人單位及相關主體
    "what": "",            // string（不可為空）：發生了什麼勞動事件
    "when": "",            // string（不可為空）：事件發生時間或時間段
    "where": "",           // string（不可為空）：事件發生地點
    "why": "",             // string（不可為空）：事件發生原因
    "how": ""              // string（不可為空）：事件經過及處理方式
  },

  "themes": [],            // enum（可多選；不可為空）：勞工議題分類
  // 勞動合同與勞動關係
  // 勞動爭議
  // 工資、報酬與最低工資
  // 工作時間與加班制度
  // 休息休假與帶薪年休假制度
  // 解除勞動合同、裁員、經濟補償與賠償
  // 職業病、醫療期與患病勞動者保護
  // 工傷保險與工傷認定
  // 社會保險與福利制度
  // 勞務派遣與非典型用工
  // 女職工與未成年工特殊保護
  // 就業促進與勞動保障監察

  "events": [
    {
      "date": {
        "event_date_start": "",   // string（YYYY-MM-DD，可為空）：單日則只填 start
        "event_date_end": ""      // string（YYYY-MM-DD，可為空）
      },

      "province": "",             // enum（僅選其一；不可為空）：事件發生省份

      "worker_identity": [],      // enum（可多選；不可為空）：工人職業身份
      // 白領受僱者
      // 藍領受僱者
      // 政府公務員或事業單位工作者
      // 攤販/店主/小業主
      // 青年學生/職校/實習生
      // 不明

      "worker_gender": [],        // string（不可為空）：工人性別分布，未提及則填入不明

      "worker_age": [],           // string（不可為空）：工人年齡分布，未提及則填入不明

      "company_identity": [],     // enum（可多選；不可為空）：資方類型
      // 國企/央企
      // 外資
      // 政府/事業單位
      // 民營企業
      // 平台企業
      // 勞務公司/派遣機構
      // 不明

      "involved_industry": [],    // enum（可多選；不可為空）：涉及行業
      // 採礦業
      // 製造業
      // 交通物流業
      // 建築業
      // 服務業
      // 黨政機關
      // 農業

      "worker_discourse": {
        "worker_individual": "",          // string（可為空）：工人個體稱呼
        "worker_personal_statement": ""   // string（可為空）：工人個體話語
      },

      "worker_situation": {
        "harm_experienced": [],           // enum（可多選；不可為空）：工人所受傷害
        // 死亡
        // 身體傷害
        // 經濟損害
        // 精神傷害
        // 人格尊嚴傷害
        // 無具體傷害
        "rights_violated": "",            // string（可為空）：工人具體受侵害權益
        "compensation_received": ""       // string（可為空）：工人所獲補償
      }
    }
  ]
}
