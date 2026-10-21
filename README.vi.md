# pythia-mongo

[English](README.md) · **Tiếng Việt**

pythia cho MongoDB: phát triển database cho AI agent, xây trên
[pythia-core](https://github.com/thaildhe172591/pythia-core). Nó nhắm làm
được điều mà [pythia](https://github.com/thaildhe172591/pythia) làm trên
Oracle, [pythia-postgres](https://github.com/thaildhe172591/pythia-postgres)
trên PostgreSQL và [pythia-mssql](https://github.com/thaildhe172591/pythia-mssql)
trên SQL Server: agent học từ database đang chạy, hỏi một người trước mọi
lần ghi, và chỉ ghi qua một cổng có snapshot, có kiểm chứng và báo cáo trung
thực.

**Alpha (0.1.1).** Nó đọc được mọi thứ mà nhịp Học của pythia cần, ghi qua
một cổng duy nhất — dữ liệu được rehearse trong một transaction; validator,
view và index được dự đoán, ghi đúng một lần rồi đọc lại — và chuẩn bị một
project cho agent: guard, bản tóm tắt đầu phiên, các cánh cửa duyệt và các
skill `pythia-mongo-*`.

| Đã dùng được |
|---|
| đọc: `check`, `ls`, `src`, `cols`, `ddl`, `grep`, `deps`, `impact`, `errors`, `connections` |
| ghi: `apply`, `deploy`, `approve`, `journal`, `history`, `policy`, `autopilot`, `lint` |
| harness: `install`, `doctor`, `hook`, `mcp`, `skill lint` |

Đã test trên MongoDB 7.0 và 8.0, mỗi bản qua toàn bộ live check; 7.0 là
phiên bản tối thiểu, và thấp hơn thì `check` nói rõ (không gì bị từ chối).

## Cài đặt

```bash
pip install pythia-mongo
```

Lệnh này kéo theo pythia-core, và [pymongo](https://pypi.org/project/pymongo/),
driver duy nhất nó dùng. Bản đang phát triển là nhánh main của cả hai:

```bash
pip install "git+https://github.com/thaildhe172591/pythia-core" \
            "git+https://github.com/thaildhe172591/pythia-mongo"
```

## Chuẩn bị một project cho agent

```bash
cd your-project
pythia-mongo install     # once; a second run changes nothing
pythia-mongo doctor      # is everything wired? exit 1 names what is not
```

`install` ghi những thứ sau, và giữ nguyên mọi thứ khác:

- `.pythia/mongo/connections.json`, mode 600, tạo một lần từ template — dev
  tự điền mật khẩu; agent không bao giờ mở file này;
- các dòng `.gitignore` cho file đó, cho các lần duyệt của máy này
  (`.pythia/mongo/grants/`) và cho `.claude/settings.local.json`;
- `.claude/settings.local.json`: các hook (guard, bản tóm tắt đầu phiên,
  câu trả lời AskUserQuestion), ghi bằng đường dẫn tuyệt đối của interpreter
  này để chúng chạy được dù virtual environment có được kích hoạt hay không,
  và các deny rule cho file của engine;
- MCP approver `pythia_mongo` (tool `pythia_mongo_approve`), chỉ trong file
  riêng của máy này: local scope của Claude Code cho project
  (`~/.claude.json`) và `~/.codex/config.toml` của Codex, mỗi cái khi client
  đó đã từng chạy ở đây;
- một khối `pythia-mongo` trong CLAUDE.md và AGENTS.md (khối của các công cụ
  khác, và chữ của chính dev, được giữ nguyên);
- các skill, trong `.claude/skills` và `.agents/skills`:
  `using-pythia-mongo` (bộ định tuyến), `pythia-mongo-explore`,
  `pythia-mongo-impact`, `pythia-mongo-apply`, `pythia-mongo-deploy`,
  `pythia-mongo-autopilot`, `pythia-mongo-verify`.

Sau khi cài, khởi động lại phiên của agent để hook được nạp. Từ đó mỗi phiên
bắt đầu bằng các luật và một dòng `STATE` (connection, write policy). Trước
mỗi lần gọi tool, guard quyết định:

| Agent chạy | Guard |
|---|---|
| `mongosh` hay `mongo` đời cũ được đưa một lần ghi (`insertOne`, `updateMany`, `deleteMany`, `replaceOne`, `drop`, `createIndex`, `createView`, `renameCollection`, `bulkWrite`, `runCommand`, `adminCommand`, `createUser`, một stage `$out` hay `$merge`, `load()`), hoặc một script (`-f`, `--file`, một file `.js` hay `.mjs`, `< file`, một pipe vào shell); `mongoimport`, `mongorestore`, `mongofiles` — kể cả sau `docker exec`, `ssh`, `sudo` hay `bash -c` | chặn: mọi lần ghi đi qua `pythia-mongo apply` |
| một tool của MCP server MongoDB có tên là một lần ghi (`insert-many`, `update-many`, `delete-many`, `drop-collection`, `create-index`, `rename-collection`, ...), hoặc được đưa một command document có ghi (`{"drop": ...}`, `{"collMod": ...}`, một stage `$merge` hay `$out`) | chặn |
| đọc `connections.json`; sửa `policy.json`, journal hay một grant; đặt `PYTHIA_MONGO_CI`; gọi `grants.mint` từ một one-liner | chặn |
| một lệnh đọc của `pythia-mongo`, một preview, `approve --card` | cho qua, không hỏi |
| `apply --confirm <token>` mà dev đã duyệt trên connection này | cho qua; apply kiểm lại |
| `mongosh` chỉ đọc, `mongodump`, `mongoexport`, `approve`, `--yes`, `policy set`, mọi lệnh ghép | đứng ngoài: client tự hỏi |

Guard đọc một lệnh theo những gì nó gọi tên, không theo ý nghĩa của nó: nó
có thể chặn một lệnh vô hại (một `find` có nhắc `.drop(` trong một chuỗi,
hoặc một `runCommand` chỉ đọc) và bỏ lọt một lần ghi được viết theo cách nó
không liệt kê. Nó thấy các lệnh mà Claude Code đưa cho các tool của mình,
không thấy Compass hay một driver bên trong ứng dụng. Cổng phía sau vẫn giữ
được trong cả hai trường hợp (SECURITY.md của pythia-core).

pythia-postgres và pythia-mssql cài cạnh nó trong cùng một project, và
pythia cho Oracle cũng vậy: mỗi bên giữ nguyên hook và khối hướng dẫn của
các bên khác, và guard cùng hook duyệt của mỗi bên chỉ hành động cho chính
công cụ của nó (CI của pythia-core kiểm tra điều này khi cả bốn cùng được
cài).

## Connection

`.pythia/mongo/connections.json` ở gốc project, chỉ chủ sở hữu được đọc
(`chmod 600`), và nằm ngoài git. Template:
[examples/connections.example.json](https://github.com/thaildhe172591/pythia-mongo/blob/main/examples/connections.example.json).

```json
{
  "default": "dev",
  "dev": { "host": "db-dev", "port": 27017, "database": "app",
           "user": "app_agent", "password": "...", "auth_source": "admin",
           "tls": false }
}
```

- `host` và `database` là bắt buộc. `host` có thể liệt kê nhiều member
  (`"a:27017,b:27017"`).
- `auth_source` là database mà user thuộc về (mặc định `admin`).
- `tls` (mặc định `false`), `replica_set`, và `direct` (`true` thì nói
  chuyện với đúng member được nêu, không phải với cả set mà nó quảng bá —
  cho một member truy cập qua port được map của container hoặc qua tunnel).
- Một connection string (`"uri"`) bị từ chối: nó mang mật khẩu vào mọi nơi
  nó được in ra.
- Entry được chọn theo `--conn NAME`, rồi `PYTHIA_MONGO_CONNECTION`, rồi
  entry duy nhất, rồi thư mục nằm ngay dưới gốc project, rồi `"default"`.
  `PYTHIA_MONGO_CONFIG` trỏ tới một file khác.

pythia cho Oracle giữ `.pythia/connections.json`, và các engine khác giữ thư
mục riêng của chúng; pythia-mongo không đọc cái nào trong số đó.

## Các lệnh

```bash
pythia-mongo check                 # server, replica set or not, database
pythia-mongo ls "t_order%"         # collections and views by LIKE pattern
pythia-mongo src t_order           # a validator, or a view's pipeline, as Extended JSON
pythia-mongo cols t_order          # fields and their types, from a sample of documents
pythia-mongo ddl t_order           # the commands that make it: create, createIndexes
pythia-mongo grep PAID             # every validator and pipeline line holding a text
pythia-mongo deps v_order_lines    # what a view reads
pythia-mongo impact t_order        # what reads it: run before changing it
pythia-mongo errors [NAME]         # documents a validator rejects, views that fail
```

`--json` cho một envelope mỗi lệnh; `--limit`, `--max-lines` và `--offset`
phân trang output dài, và mọi chỗ bị cắt đều nói cách lấy phần còn lại.

### Những gì MongoDB không thấy, và pythia-mongo nói ra thế nào

- **Không có catalog phụ thuộc.** MongoDB chỉ ghi lại view: `impact` đi qua
  `viewOn` của mọi view và các collection mà pipeline của nó đọc
  (`$lookup`, `$graphLookup`, `$unionWith`, `$facet`, cả pipeline lồng
  nhau). Code ứng dụng đọc và ghi một collection qua driver thì database
  không thấy, và view ở database khác, job `$merge` / `$out` theo lịch và
  change stream cũng vậy. Mỗi điểm mù đều được in ra mỗi lần.
- **Không có danh sách cột.** `cols` đọc tối đa 1000 document lấy mẫu: mỗi
  đường dẫn field (`address.city`, `tags[]` cho phần tử của một mảng), các
  kiểu của nó theo số document mang chúng, bao nhiêu document có nó, và
  validator `$jsonSchema` nói gì (required, description). Một field mà
  validator khai báo nhưng không document mẫu nào có được liệt kê là
  `0 of N`. Khi collection có nhiều hơn mẫu, nó nói rõ.
- **`errors` đếm, nó không compile.** Với mỗi collection có validator: bao
  nhiêu document đang vi phạm nó, kèm document đầu tiên (`warning` khi
  validator chỉ cảnh báo). Mỗi view chạy trên 100 document đầu của nó, và
  một view đọc một collection không tồn tại thì được nêu tên. Một collection
  không có validator thì không có gì để kiểm, và output ghi `NOT VERIFIED`.
- **`ddl` được dựng lại, không phải dump:** một mảng JSON các command
  document tạo ra collection (`create` với validator và option của nó,
  `createIndexes`) hoặc view. Live check drop từng cái, chạy chúng, dựng lại
  và so sánh.
- **Lệnh đọc không bao giờ ghi, và server là lớp bảo vệ thứ hai.** MongoDB
  không có phiên chỉ đọc. Mọi command mà một lệnh đọc gửi đi là một file
  trong `src/pythia_mongo/commands/`, và bộ test giữ chúng chỉ được đọc; một
  user chỉ có role `read` là thứ server thực thi.

### Ghi: cổng

```bash
pythia-mongo apply change.json                   # preview: rehearsed or predicted, nothing kept
pythia-mongo approve 3fa9c1                      # the developer approves, at their own console
pythia-mongo apply change.json --confirm 3fa9c1  # writes it — only as approved
pythia-mongo journal restore <entry>             # undo is a write too: preview, approve, confirm
pythia-mongo policy                              # which groups may be written, and is rollback real?
```

Dev duyệt qua cánh cửa đầu tiên dùng được:

1. **Trong chat của Claude Code.** Agent hỏi bằng AskUserQuestion, nội dung
   đúng nguyên văn output của `pythia-mongo approve --card <token>`, hai lựa
   chọn Approve / Reject. Hook nhận câu trả lời chỉ ghi nhận lần duyệt khi
   câu hỏi mang đúng thẻ đó và chính dev chọn Approve — không phải câu trả
   lời do agent viết, không phải một hộp thoại tự đóng khi không có ai.
2. **Qua MCP approver** (`pythia_mongo_approve`; Codex bắt đầu từ đây):
   client hiện thẻ, và chỉ một lần Approve rõ ràng mới được tính.
3. **Ở console của dev:** `pythia-mongo approve <token>`.

`pythia-mongo doctor` cảnh báo những thiết lập có thể tự trả lời cánh cửa
chat thay cho dev (chế độ `dontAsk`, một allow rule cho AskUserQuestion, một
hook khớp mọi tool).

Mỗi file chứa **một command document**, bằng Extended JSON — đúng document
mà MongoDB nhận, không phải JavaScript của mongosh:

```json
{"update": "t_order",
 "updates": [{"q": {"status": "DRAFT"}, "u": {"$inc": {"total": 1}}, "multi": true}]}
```

`apply` xếp nó vào một group, và policy quyết định: `source` — một view
(`create` có `viewOn`, `collMod` của `viewOn` và `pipeline`) hoặc một
validator (`collMod` của `validator`, `validationLevel`,
`validationAction`) — cần dev duyệt; `structural` (một collection mới,
`createIndexes`, `dropIndexes`, `drop`, các option `collMod` khác) và
`data_dml` (`insert`, `update`, `delete`) bị từ chối cho tới khi dev chạy
`pythia-mongo policy set <group> confirm` ở console.

**Dữ liệu được rehearse.** Một insert, update hay delete chạy trong một
transaction rồi bị hủy: preview hiện số document nó đã chạm tới, và một
UPDATE hay DELETE được duyệt trên chính các document của nó — số lượng, một
mẫu, và một dấu vân tay (`$toHashedIndexKey` trên từng document). Nếu có
document nào thêm vào, rời đi hay thay đổi trước lúc confirm, lần confirm bị
từ chối. Một document bị validator từ chối làm rehearsal thất bại (MongoDB
báo điều đó trong reply, không phải dưới dạng lỗi, và pythia-mongo đọc
reply). Transaction cần một replica set: trên một server standalone, lần ghi
dữ liệu bị từ chối — một replica set một node là đủ để phát triển.

**Mọi thứ khác được dự đoán.** MongoDB chạy một view, một validator, một
index hay việc drop một collection bên ngoài mọi transaction, nên không có
gì có thể chạy rồi rollback. Predict tier của pythia-core tiếp quản: không có
gì chạy trước khi được duyệt, và preview ghi "predicted — nothing ran".

| Command | Dự đoán | Đọc lại sau khi ghi |
|---|---|---|
| một validator (`collMod`) | đếm các document mà validator mới sẽ từ chối, kèm document đầu tiên; một validator mà MongoDB sẽ từ chối thì không có gì để duyệt | validator như đã lưu, và đếm lại — số khác thì exit 3 |
| một view (`create`, `collMod`) | chạy pipeline trên không document nào (MongoDB có chấp nhận nó không?) và tới 100 document đầu (nó có chạy không?); nêu tên những gì nó đọc mà không tồn tại; chạy mọi view xây trên nó, đặt lên trên pipeline mới | view như đã lưu, và chạy lại mọi thứ — một lỗi mà dự đoán không thấy thì exit 3 |
| một unique index | tìm các key mà nó sẽ gặp hai lần (áp dụng partial filter hay sparse rule của nó); có trùng thì không có gì để duyệt | mỗi index có mặt, với key của nó |
| một index, một lệnh drop | một tên index đã tồn tại với key khác thì bị từ chối; một lệnh drop nêu tên mọi view đọc thứ nó drop | index có mặt, hoặc đã mất |

Sau khi được duyệt, core chạy command đúng một lần. MongoDB áp dụng mỗi
command này trọn vẹn hoặc không gì cả, nên một lần từ chối không ghi gì và
giữ nguyên lần duyệt; một command mà câu trả lời không bao giờ tới được báo
`WRITTEN?` (exit 3). Cái đã ghi được đọc lại, và mọi thứ khác với dự đoán
đều được báo ra và exit 3 kèm lệnh restore. Một dự đoán chạy tối đa 30 giây
(`maxTimeMS`).

**Bị từ chối, kèm lý do:** JavaScript của mongosh, nhiều command trong một
file, một key viết hai lần, JavaScript ở bất kỳ đâu (`$where`, `$function`,
`$accumulator`, code), `$out` và `$merge` (một dự đoán chạy pipeline trước
khi được duyệt: nó không bao giờ được ghi), lệnh đọc (`aggregate`, `find`),
`findAndModify`, một upsert, một update hay delete chạm một document trong
nhiều document (`"multi": true` hoặc `"limit": 0`, hoặc gọi đúng nó bằng
`_id`), user và role, `renameCollection`, `dropDatabase`,
`bypassDocumentValidation`, các field của session và transaction (`lsid`,
`writeConcern`, ...), và các collection `system.`.

### Một release: `deploy`, một transaction

```bash
pythia-mongo deploy 01_fix.json 02_backfill.json                     # preview the release as one transaction
pythia-mongo deploy 01_fix.json 02_backfill.json --confirm 9c41e0b2aa  # all of it, as approved, or none
```

Một release là dữ liệu: một hay nhiều file, mỗi file là một command
document hoặc một mảng JSON các command document, theo thứ tự chúng chạy.
Nó được rehearse trong một transaction — từng command theo thứ tự, các
document của nó được đếm và lấy dấu vân tay tại đúng thời điểm của nó (một
update trên một document mà chính release insert sẽ thấy document đó), rồi
tất cả bị hủy. Một thẻ hiện mọi command, và một lần duyệt (token 10 chữ số,
qua cùng các cánh cửa) phủ cả release; token của một command lẻ không được
duyệt riêng. Lúc confirm, nó kiểm từng command giống hệt từng byte với bản
đã duyệt trước khi chạy gì, chạy lại release trong một transaction, và chỉ
commit nếu mọi command vẫn khớp. Một command lỗi, hoặc document đã thay đổi,
sẽ hủy cả release. Một lần commit không có câu trả lời được báo `WRITTEN?`
cho cả release.

Một validator, một view, một index hay một collection mới hoặc bị drop không
có chỗ trong một release: MongoDB chạy chúng bên ngoài mọi transaction, nên
chúng được dự đoán, không được rehearse, và không thể vào hết hoặc không vào
gì. `deploy` từ chối chúng trước khi ghi bất cứ gì; hãy apply từng cái
riêng. Mọi thứ `apply` từ chối cũng bị từ chối ở đây.

### Lint: trước mọi lần apply

```bash
pythia-mongo lint 01_fix.json 02_view.json   # a change's files in one run
pythia-mongo lint --rules                    # every rule and its effective severity
```

Các rule đọc những gì MongoDB chấp nhận mà một người review thì không:

| Rule | Mặc định | Vì sao |
|---|---|---|
| `mongo-validation-warn` | warn | `validationAction: "warn"` vẫn ghi mọi document vi phạm validator, và chỉ ghi log |
| `mongo-validation-off` | warn | `validationLevel: "off"` giữ validator nhưng không thực thi gì |
| `mongo-validator-required` | info | một `$jsonSchema` không có danh sách `required` chấp nhận cả document không có field nào của nó |
| `mongo-collection-validator` | warn | một collection mới có validator của nó trong cùng thay đổi (một `collMod` của nó có đặt validator thì được tính) |
| `mongo-unique-optional` | warn | một unique index coi mọi document thiếu field là `null`, và từ chối document thứ hai — hãy làm nó partial (`$exists`) hoặc sparse |
| `mongo-ttl` | warn | một TTL index xóa document theo lịch của server, không ai hỏi và không có journal |
| `mongo-update-replacement` | warn | một update có `u` không chứa operator nào sẽ thay thế từng document, xóa mọi field mà nó không nêu |

Những gì MongoDB tự từ chối được để cho rehearsal hoặc dự đoán. Team đặt
severity và quy ước đặt tên (tên của một view, `VIEW`; collection của một
validator, `VALIDATOR`) trong `.pythia/mongo/lint.json`:

```json
{"severity": {"mongo-validation-warn": "error", "naming": "error"},
 "naming": {"VIEW": "^v_[a-z0-9_]+$"}}
```

Mọi preview đều hiện các phát hiện, lỗi của một command nằm trên thẻ của nó,
và autopilot không bao giờ ghi một thay đổi còn lỗi lint.

### Autopilot: một lease thay cho từng lần duyệt

```bash
pythia-mongo autopilot request --groups source --hours 2 --max-writes 30
pythia-mongo autopilot report      # every write under the lease, with its restore
pythia-mongo autopilot off         # anyone may revoke
```

Khi dev muốn agent làm việc mà không phải duyệt từng lần ghi, agent xin một
lease. Thẻ của nó nêu connection, các group, thời gian, số lần ghi và có gồm
command phá hủy hay không, và chưa có gì được ủy quyền cho tới khi dev duyệt
nó qua một cánh cửa (hoặc tự chạy `pythia-mongo autopilot on` ở console).
Trong thời gian lease còn hiệu lực, `apply` và `deploy` ghi những gì nó phủ
mà không cần `--confirm` — vẫn có snapshot, rehearse hoặc dự đoán, đọc lại
và ghi journal. Lease không bao giờ phủ một connection khác, một connection
đánh dấu `"protected": true` (hoặc có `"env"` là prod / production / prd /
live), một group hay command phá hủy mà thẻ không nêu, hoặc quá 1000
document; một lần ghi làm gãy thứ gì đó, ghi ra khác với dự đoán hoặc là
`WRITTEN?`, hoặc năm lần thất bại liên tiếp, sẽ tạm dừng nó.

### Quyền tối thiểu

Các lệnh đọc cần role `read` trên database. Ghi cần `readWrite` (dữ liệu,
index, collection và view mới) và `dbAdmin` (`collMod` của một validator
hay một view); preview cảnh báo khi user có nhiều quyền hơn hẳn (`root`,
`dbOwner`, bất kỳ role `AnyDatabase` nào). Live check chạy mọi lệnh đọc bằng
một user `read`, và mọi lần ghi bằng một user có `readWrite` và `dbAdmin`.

## Mỗi command là một file

Giống các file query của các engine SQL, mọi command mà pythia-mongo gửi đi
nằm trong `src/pythia_mongo/commands/` dưới dạng JSON: nó dùng để làm gì,
các bind của nó, nó trả về gì, và command document. Một bind được viết là
`{"$bind": "name"}` ở chỗ giá trị của nó đặt vào, nên chữ do một người hay
một agent đưa vào luôn rơi vào vị trí một giá trị — không bao giờ thành một
operator, một stage hay một command riêng. Bộ test kiểm rằng mỗi file khai
báo đúng các bind nó dùng, không chứa JavaScript (`$where`, `$function`,
`$accumulator`), và không chứa lần ghi, `$out` hay `$merge` nào: mọi file
command đều chỉ đọc. Lần ghi duy nhất mà pythia-mongo từng gửi là command
document của chính dev — trong transaction của một rehearsal, hoặc đúng một
lần sau khi được duyệt.

## Test

```bash
python tests/test_mongo.py    # no database, no pymongo — mutation-checked
python tests/live_check.py    # a disposable server only (see its docstring)
```

CI chạy bộ test trên Ubuntu, Windows và macOS, Python 3.9 và 3.13, và live
check — mọi lệnh đọc, mọi đường ghi, một release, một phát hiện lint trong
một preview thật và một lần ghi dưới lease — với MongoDB 7.0 và 8.0, mỗi bản
là một replica set một node có xác thực. Nó test với nhánh pythia-core cùng
tên khi có.

## Giấy phép

MIT
