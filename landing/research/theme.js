// Shared theme toggle for OrionFlow research pages.
(function(){
  var tb = document.getElementById("theme");
  if(!tb) return;
  tb.addEventListener("click", function(){
    var d = document.documentElement;
    var next = d.getAttribute("data-theme") === "dark" ? "light" : "dark";
    d.setAttribute("data-theme", next);
    try{ localStorage.setItem("of-theme", next); }catch(e){}
  });
})();
