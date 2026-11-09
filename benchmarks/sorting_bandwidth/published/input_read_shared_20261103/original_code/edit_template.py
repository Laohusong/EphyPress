from pathlib import Path
p=Path(__file__).with_name('report_template.html')
s=p.read_text(encoding='utf-8')
s=s.replace('原 raw 与旧压缩曲线为历史对照</p>','原 raw 与旧压缩曲线为历史对照；另补一个同轮5000 MB/s raw锚点</p>')
s=s.replace('<section><h2>七档完整数据</h2>','<section><h2>同轮高带宽 raw 对照</h2><p id="anchor" class="notice"></p><p class="muted">这个额外对照用于核验本轮计算耗时；没有用一个点推算或替换整条历史 raw 曲线。</p></section><section><h2>七档完整数据</h2>')
s=s.replace("el('details').textContent=", "el('anchor').textContent='新增同轮5000 MB/s raw：'+duration(DATA.anchor.seconds)+'，共享缓存：'+duration(DATA.rows.find(r=>r.series==='shared'&&r.rate===5000).seconds)+'；raw/共享耗时比 '+DATA.anchor.contemporaneous_raw_over_shared.toFixed(3)+'×。两者最终数组一致：'+DATA.anchor.same_arrays_as_new_shared+'。';el('details').textContent=")
p.write_text(s,encoding='utf-8')
