function confirmDelete(url) {
  if (window.confirm("دڵنیایت لە سڕینەوەی ئەم کاڵایە؟")) {
    const form = document.createElement("form");
    form.method = "POST";
    form.action = url;
    document.body.appendChild(form);
    form.submit();
  }
}