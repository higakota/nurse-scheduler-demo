(() => {
const form=document.getElementById("advance-availability-form");
if(!form)return;
const inputs=[...form.querySelectorAll("[data-advance-key]")];
const original=new Map(inputs.map(input=>[input,input.value]));
form.addEventListener("change",()=>{
const changes={};
for(const input of inputs)if(input.value!==original.get(input))changes[input.dataset.advanceKey]=input.value;
document.getElementById("advance-availability-changes").value=JSON.stringify(changes);
document.getElementById("advance-availability-save").disabled=!Object.keys(changes).length;
});
})();
