from django.shortcuts import render, get_object_or_404, redirect
from django.contrib import messages
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from .forms import ResultUploadForm, SkaterEditForm
from core.models import Event, ScheduledSkater, Skater
from .image_utils import detect_and_crop_document
from django.core.files.storage import default_storage
from django.core.files.base import ContentFile
import uuid

from django.contrib.auth.decorators import login_required

@login_required
def dashboard(request):
    events = Event.objects.order_by("date", "eventNumber")
    return render(request, "staffadmin/dashboard.html", {"events": events})

@login_required
def upload_results(request, event_id):
    event   = get_object_or_404(Event, pk=event_id)
    # grab this once so we can both render and update scratches
    #skaters = ScheduledSkater.objects.filter(event=event).select_related('skater__club')
   # Always fetch skaters in ascending orderNumber
    skaters = (
        ScheduledSkater.objects
        .filter(event=event)
        .select_related('skater__club')
        .order_by('orderNumber')
    )

    # --- New code: find previous/next events ---
    # Prev = max eventNumber < this one
    previous_event = (
        Event.objects
             .filter(eventNumber__lt=event.eventNumber)
             .order_by('-eventNumber')
             .first()
    )
    # Next = min eventNumber > this one
    next_event = (
        Event.objects
             .filter(eventNumber__gt=event.eventNumber)
             .order_by('eventNumber')
             .first()
    )
    
    if request.method == "POST":
        # 0) update scratches
        for s in skaters:
            key = f"scratch_{s.id}"
            new_val = key in request.POST
            if s.scratch != new_val:
                s.scratch = new_val
                s.save()

        # 1) update orderNumber from editable textbox
        for s in skaters:
            field = f'order_{s.id}'
            new_order = request.POST.get(field)
            if new_order is not None:
                try:
                    ord_int = int(new_order)
                except ValueError:
                    ord_int = s.orderNumber  # fallback on bad input
                if ord_int != s.orderNumber:
                    s.orderNumber = ord_int
                    s.save(update_fields=['orderNumber'])

        # 1) persist the chosen image URL (allow blank → null)
        external_url = (
            request.POST.get("external_image_url", "") or
            request.POST.get("image_url", "")
        ).strip()
        event.external_image_url = external_url or None


        # 2) update status
        selected_status = request.POST.get("status", event.status)
        if selected_status in dict(Event.STATUS_CHOICES):
            event.status = selected_status


        event.display = 'display' in request.POST

        try:
            event.save()
            skaters = (
                ScheduledSkater.objects
                .filter(event=event)
                .select_related('skater__club')
                .order_by('orderNumber')
            )
            messages.success(request, "Result saved successfully.")
        except Exception as e:
            messages.error(request, f"Failed to save event: {e}")

     # stay on the same page after saving
    return render(request, "staffadmin/upload_results.html", {
        "event": event,
        "form": ResultUploadForm(),
        "scheduled_skaters": skaters,
        "previous_event": previous_event,
        "next_event": next_event,
    })

@csrf_exempt
def ajax_process_image(request, event_id):
    if request.method != 'POST':
        return JsonResponse({'error': 'Invalid request method'}, status=405)

    # accept either 'file' or 'image' as the field name
    image_file = request.FILES.get('file') or request.FILES.get('image')
    if not image_file:
        return JsonResponse({'error': 'No image provided'}, status=400)

    # generate a unique key
    uid = uuid.uuid4().hex
    try:
        # save original
        # 1) save the original upload
        temp_orig_path = f"temp/{uid}.jpg"
        default_storage.save(temp_orig_path, image_file)

       # 2) open it again and wrap in a file-like stream
        import io
        with default_storage.open(temp_orig_path, "rb") as f:
            img_stream = io.BytesIO(f.read())

        # 3) process & crop document from that stream
        processed_buf = detect_and_crop_document(img_stream)
        
        default_storage.save(f"temp/{uid}_cropped.jpg", processed_buf)
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)

    # return URLs for both versions
    return JsonResponse({
        'uid': uid,
        'original': default_storage.url(f"temp/{uid}.jpg"),
        'processed': default_storage.url(f"temp/{uid}_cropped.jpg"),
    })


def skater_list(request):
    skaters = Skater.objects.select_related("club").order_by("lastName", "firstName")
    return render(request, "staffadmin/skater_list.html", {"skaters": skaters})


def edit_skater(request, skater_id, scheduled_id):
    scheduled = get_object_or_404(ScheduledSkater, pk=scheduled_id)
    form = SkaterEditForm(request.POST or None, instance=scheduled.skater)
    if form.is_valid():
        form.save()
        return redirect("staff_upload_results", event_id=scheduled.event.id)
    return render(request, "staffadmin/edit_skater.html", {"form": form, "scheduled": scheduled})
