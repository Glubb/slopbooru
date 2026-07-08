function require_script_version(v)
{
	if(v!="3.a") alert("The board has been upgraded. You need to force a reload in your browser to complete the update.\nThis is usually done by holding down Shift and pressing the reload button.");
}

var style_cookie = null;  // prevent ReferenceError in legacy code; our templates use inline theme switcher

function show(id)
{
	var style=document.getElementById(id).style;
	if(style.display) style.display="";
	else style.display="none";
}

function insert(text,thread)
{
	var textarea=document.getElementById("postform"+thread).comment;
	if(textarea)
	{
		if(textarea.createTextRange && textarea.caretPos) // IE
		{
			var caretPos=textarea.caretPos;
			caretPos.text=caretPos.text.charAt(caretPos.text.length-1)==" "?text+" ":text;
		}
		else if(textarea.setSelectionRange) // Firefox
		{
			var start=textarea.selectionStart;
			var end=textarea.selectionEnd;
			textarea.value=textarea.value.substr(0,start)+text+textarea.value.substr(end);
			textarea.setSelectionRange(start+text.length,start+text.length);
		}
		else
		{
			textarea.value+=text+" ";
		}
		textarea.focus();
	}
}

function w_insert(text,link)
{
	if(document.body.className=="mainpage") document.location=link+"#i"+text;
	else insert(text,"");
}

function size_field(id,rows) { document.getElementById(id).comment.setAttribute("rows",rows); }



function delete_post(thread,post,file)
{
	if(!confirm("Are you sure you want to delete reply "+post+"?")) return;

	var fileonly=false;
	var base=document.forms[0].action.split("?")[0];
	var password=document.forms[0].password.value;

	if(file) fileonly=confirm("Leave the reply text and delete the only file?");

	var form=document.createElement("form");
	form.method="POST";
	form.action=base;
	form.style.display="none";

	function add(name,val){
		var i=document.createElement("input");
		i.type="hidden"; i.name=name; i.value=val;
		form.appendChild(i);
	}
	add("task","delete");
	add("delete",thread+","+post);
	add("password",password);
	add("fileonly",fileonly?"1":"0");

	document.body.appendChild(form);
	form.submit();
}

function preview_post(formid,thread)
{
	var form=document.getElementById(formid);
	var preview=document.getElementById("preview"+thread);

	if(!form||!preview) return;

	preview.style.display="";
	preview.innerHTML="<em>Loading...</em>";

	var text;
	text="task=preview";
	text+="&comment="+encodeURIComponent(form.comment.value);
	text+="&markup="+encodeURIComponent(form.markup.value);
	if(thread) text+="&thread="+thread;

	var xmlhttp=get_xmlhttp();
	xmlhttp.open("POST",self);
	xmlhttp.onreadystatechange=function() {
		if(xmlhttp.readyState==4) preview.innerHTML=xmlhttp.responseText;
	}
	if(is_ie()||xmlhttp.setRequestHeader) xmlhttp.setRequestHeader("Content-Type","application/x-www-form-urlencoded");
	xmlhttp.send(text);
}

function get_xmlhttp()
{
	var xmlhttp;
	try { xmlhttp=new ActiveXObject("Msxml2.XMLHTTP"); }
	catch(e1)
	{
		try { xmlhttp=new ActiveXObject("Microsoft.XMLHTTP"); }
		catch(e1) { xmlhttp=null; }
	}

	if(!xmlhttp && typeof XMLHttpRequest!='undefined') xmlhttp=new XMLHttpRequest();

	return(xmlhttp);
}

function is_ie()
{
	return(document.all&&!document.opera);
}



function set_new_inputs(id)
{
	var el=document.getElementById(id);

	if(!el||!el.link) return;

	if(!el.field_a.value) el.field_a.value=get_cookie("name");
	if(!el.field_b.value) el.field_b.value=get_cookie("link");
	if(!el.password.value) el.password.value=get_password("password");
	if(el.markup&&!el.comment.value) el.markup.value=get_cookie("markup");
	select_markup(el.markup);
}

function set_delpass(id)
{
	with(document.getElementById(id)) password.value=get_cookie("password");
}

function make_password()
{
	var chars="abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789";
	var pass='';

	for(var i=0;i<8;i++)
	{
		var rnd=Math.floor(Math.random()*chars.length);
		pass+=chars.substring(rnd,rnd+1);
	}

	return(pass);
}

function get_password(name)
{
	var pass=get_cookie(name);
	if(pass) return pass;
	return make_password();
}

function select_markup(sel)
{
	if(!window.markup_descriptions) return;

	var el=sel;
	while(el=el.nextSibling) if(el.nodeName.toLowerCase()=="small") break;

	if(el) el.innerHTML=markup_descriptions[sel.value];
}



function get_cookie(name)
{
	with(document.cookie)
	{
		var regexp=new RegExp("(^|;\\s+)"+name+"=(.*?)(;|$)");
		var hit=regexp.exec(document.cookie);
		if(hit&&hit.length>2) return unescape(hit[2]);
		else return '';
	}
};

function set_cookie(name,value,days)
{
	if(days)
	{
		var date=new Date();
		date.setTime(date.getTime()+(days*24*60*60*1000));
		var expires="; expires="+date.toGMTString();
	}
	else expires="";
	document.cookie=name+"="+value+expires+"; path=/";
}

function set_stylesheet(styletitle)
{
	var links=document.getElementsByTagName("link");
	var found=false;
	for(var i=0;i<links.length;i++)
	{
		var rel=links[i].getAttribute("rel");
		var title=links[i].getAttribute("title");
		if(rel.indexOf("style")!=-1&&title)
		{
			links[i].disabled=true; // IE needs this to work. IE needs to die.
			if(styletitle==title) { links[i].disabled=false; found=true; }
		}
	}
	if(!found) set_preferred_stylesheet();
}

function set_preferred_stylesheet()
{
	var links=document.getElementsByTagName("link");
	for(var i=0;i<links.length;i++)
	{
		var rel=links[i].getAttribute("rel");
		var title=links[i].getAttribute("title");
		if(rel.indexOf("style")!=-1&&title) links[i].disabled=(rel.indexOf("alt")!=-1);
	}
}

function get_active_stylesheet()
{
	var links=document.getElementsByTagName("link");
	for(var i=0;i<links.length;i++)
	{
		var rel=links[i].getAttribute("rel");
		var title=links[i].getAttribute("title");
		if(rel.indexOf("style")!=-1&&title&&!links[i].disabled) return title;
	}
}

function get_preferred_stylesheet()
{
	var links=document.getElementsByTagName("link");
	for(var i=0;i<links.length;i++)
	{
		var rel=links[i].getAttribute("rel");
		var title=links[i].getAttribute("title");
		if(rel.indexOf("style")!=-1&&rel.indexOf("alt")==-1&&title) return title;
	}
	return null;
}



window.onunload=function(e)
{
	if(style_cookie)
	{
		var title=get_active_stylesheet();
		set_cookie(style_cookie,title,365);
	}
}

window.onload=function(e)
{
	if(match=/#i(.+)/.exec(document.location.toString()))
	if(!document.getElementById("postform").comment.value)
	insert(unescape(match[1]),"");
}

if(style_cookie)
{
	var cookie=get_cookie(style_cookie);
	var title=cookie?cookie:get_preferred_stylesheet();
	set_stylesheet(title);
}

var captcha_key=make_password();

/* Image expansion - click thumbnail to expand in place, click again to shrink.
   Matches 4chan behavior: left click toggles expand (prevents nav), ctrl/middle/shift opens full in tab.
   The image *itself* receives the click for expansion (the <img> is the primary target).
*/
function expand_image(link) {
  var img = link;
  if (link && link.tagName && link.tagName.toLowerCase() === 'img') {
    // called with img directly: find containing link for .href if present
    img = link;
    var parentLink = link.closest ? link.closest('a[href]') : link.parentNode;
    if (parentLink && parentLink.href) link = parentLink;
  } else {
    img = link ? link.querySelector('img') : null;
  }
  if (!img) return;
  var post = (link && link.closest) ? link.closest('.post') : (img.closest ? img.closest('.post') : null);
  if (img.classList.contains('expanded')) {
    // shrink
    if (img.dataset.origSrc) img.src = img.dataset.origSrc;
    if (img.dataset.origWidth) img.style.width = img.dataset.origWidth;
    if (img.dataset.origHeight) img.style.height = img.dataset.origHeight;
    img.classList.remove('expanded');
    if (post) post.classList.remove('has-expanded-image');
  } else {
    img.dataset.origSrc = img.src;
    img.dataset.origWidth = img.style.width || img.width + 'px';
    img.dataset.origHeight = img.style.height || img.height + 'px';
    // Prefer link.href for the full-size URL (the semantic link around the thumb)
    var fullUrl = (link && link.href) ? link.href : (img.dataset.full || img.src);
    img.src = fullUrl;
    img.style.width = '';
    img.style.height = '';
    img.classList.add('expanded');
    if (post) post.classList.add('has-expanded-image');
  }
}

document.addEventListener('DOMContentLoaded', function() {
  // Attach directly to the thumbnail *images* themselves so the image is the link/target for expansion.
  // We still use the wrapping <a class="fileThumb" href="full"> for right-click/save and modifier behavior.
  var thumbImgs = document.querySelectorAll('.file a[href] img, a.fileThumb img, img.fileThumb');
  for (var i = 0; i < thumbImgs.length; i++) {
    var img = thumbImgs[i];
    img.addEventListener('click', function(ev) {
      // Find the containing link (for href + to pass to expand_image)
      var link = this.closest ? this.closest('a[href]') : this.parentNode;
      if (!link || !link.href) link = this; // fallback (rare)
      // allow open in new tab etc with modifiers or middle click
      if (ev.ctrlKey || ev.metaKey || ev.shiftKey || ev.which === 2) {
        return; // let browser default (target=_blank will open tab)
      }
      ev.preventDefault();
      expand_image(link);
    });
  }
});

/* Also add CSS rule via JS if needed, but better in stylesheet.
   For expanded images, remove max size constraints.
*/

/* Quote / reply button: clicking a post number (or .quotejs) inserts >>num into the comment textarea.
   Matches vichan/4chan behavior. */
function quote(post) {
	var ta = document.querySelector('textarea[name="comment"]');
	if (!ta) {
		// fallback for other forms
		var tas = document.getElementsByName('comment');
		ta = tas[tas.length - 1];
	}
	if (!ta) return;

	var insert = '>>' + post + '\n';
	var val = ta.value;
	if (val.length > 0 && val[val.length - 1] !== '\n') {
		insert = '\n' + insert;
	}

	// insert at current cursor position (or end)
	var start = (ta.selectionStart !== undefined) ? ta.selectionStart : val.length;
	var end = (ta.selectionEnd !== undefined) ? ta.selectionEnd : val.length;
	ta.value = val.substring(0, start) + insert + val.substring(end);

	var newPos = start + insert.length;
	ta.selectionStart = newPos;
	ta.selectionEnd = newPos;
	ta.focus();

	// scroll the form into view if possible
	var form = ta.form || ta.closest('form');
	if (form && form.scrollIntoView) {
		form.scrollIntoView({ block: 'center', behavior: 'smooth' });
	}
}

document.addEventListener('DOMContentLoaded', function() {
	// Make >> quotelinks (in post text) also trigger quoting when clicked (standard 4chan/vichan behavior).
	// We still let the default hash navigation happen so it scrolls to the referenced post.
	var quotelinks = document.querySelectorAll('a.quotelink, .postMessage a[href*="/"], .postMessage a[href^="/"]');
	for (var i = 0; i < quotelinks.length; i++) {
		(function(a) {
			a.addEventListener('click', function(ev) {
				var m = a.textContent.match(/>>(\d+)/);
				if (!m) {
					// fallback parse from href or text
					var txt = a.textContent || a.innerText || '';
					m = txt.match(/>>(\d+)/);
				}
				if (m) {
					// quote insertion (does not prevent the anchor navigation/scroll)
					quote(m[1]);
				}
			});
		})(quotelinks[i]);
	}
});
