(() => {
  'use strict';
  document.querySelectorAll('[data-options-editor]').forEach(editor => {
    const hidden=editor.querySelector('input[name=options]'); const list=editor.querySelector('[data-option-list]'); const add=editor.querySelector('[data-add-option]');
    let options=[]; try { options=JSON.parse(hidden.value); } catch (_) { options=[]; }
    function sync() { hidden.value=JSON.stringify([...list.children].map(row=>({id:row.dataset.optionId,name:row.querySelector('[data-option-name]').value.trim(),price:Number(row.querySelector('[data-option-price]').value)}))); }
    function row(option) {
      const wrapper=document.createElement('div');wrapper.className='option-row';wrapper.dataset.optionId=option.id || `extra_${Date.now().toString(36)}_${Math.random().toString(36).slice(2,8)}`;
      const name=document.createElement('input');name.type='text';name.className='control';name.maxLength=100;name.required=true;name.value=option.name || '';name.placeholder='ชื่อตัวเลือก';name.dataset.optionName='';name.setAttribute('aria-label','ชื่อตัวเลือกเพิ่มเติม');
      const price=document.createElement('input');price.type='number';price.className='control';price.min='0';price.max='100000';price.step='.01';price.required=true;price.value=option.price??0;price.dataset.optionPrice='';price.setAttribute('aria-label','ราคาเพิ่ม บาท');
      const remove=document.createElement('button');remove.type='button';remove.className='btn btn-danger btn-small';remove.textContent='×';remove.setAttribute('aria-label','ลบตัวเลือก');remove.addEventListener('click',()=>{wrapper.remove();sync();});
      wrapper.append(name,price,remove);list.append(wrapper);name.addEventListener('input',sync);price.addEventListener('input',sync);
    }
    options.forEach(row);add.hidden=false;add.addEventListener('click',()=>{if(list.children.length>=30){window.showToast('เพิ่มตัวเลือกได้ไม่เกิน 30 รายการ',true);return;}row({});sync();list.lastElementChild.querySelector('input').focus();});
    editor.closest('form').addEventListener('submit',sync);
  });
})();
