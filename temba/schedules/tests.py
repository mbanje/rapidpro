from __future__ import unicode_literals

from datetime import datetime, timedelta
from django.utils import timezone
import json
import time
from django.core.urlresolvers import reverse
from django.contrib.auth.models import User, Group
from .models import Schedule
from dateutil.relativedelta import relativedelta
from temba.msgs.models import Broadcast
from temba.orgs.models import Org
from temba.tests import TembaTest
import pytz

MONDAY = 0     # 2
TUESDAY = 1    # 4
WEDNESDAY = 2  # 8
THURSDAY = 3   # 16
FRIDAY = 4     # 32
SATURDAY = 5   # 64
SUNDAY = 6     # 128


class ScheduleTest(TembaTest):

    def create_schedule(self, repeat_period, repeat_days=[], start_date=None):

        if not start_date:
            # Test date is 10am on a Thursday, Jan 3rd
            start_date = datetime(2013, 1, 3, hour=10).replace(tzinfo=pytz.utc)

        # create a our bitmask from repeat_days
        bitmask = 0
        for day in repeat_days:
            bitmask += pow(2, (day + 1) % 7)

        return Schedule.create_schedule(start_date, repeat_period, self.user, bitmask)

    def test_get_days_bitmask(self):
        now = timezone.now()
        sched = Schedule.create_schedule(now, "W", self.user, 244)
        self.assertEquals(sched.get_days_bitmask(), ['4', '16', '32', '64', '128'])

    def test_schedule(self):
        # updates two days later on Saturday
        tomorrow = timezone.now() + timedelta(days=1)
        sched = self.create_schedule('W', [THURSDAY, SATURDAY], start_date=tomorrow)

        self.assertTrue(sched.has_pending_fire())
        self.assertEquals(sched.status, 'S')

        self.assertEquals(sched.get_repeat_days_display(), ['Thursday', 'Saturday'])

        sched.unschedule()
        self.assertEquals(sched.status, 'U')

    def test_next_fire(self):

        # updates two days later on Saturday
        sched = self.create_schedule('W', [THURSDAY, SATURDAY])

        self.assertEquals(sched.repeat_days, 80)
        self.assertEquals(datetime(2013, 1, 5, hour=10).replace(tzinfo=timezone.pytz.utc), sched.get_next_fire(sched.next_fire))

        # updates six days later on Wednesday
        sched = self.create_schedule('W', [WEDNESDAY, THURSDAY])
        self.assertEquals(datetime(2013, 1, 9, hour=10).replace(tzinfo=timezone.pytz.utc), sched.get_next_fire(sched.next_fire))

        # since we are starting thursday, a thursday should be 7 days out
        sched = self.create_schedule('W', [THURSDAY])
        self.assertEquals(datetime(2013, 1, 10, hour=10).replace(tzinfo=timezone.pytz.utc), sched.get_next_fire(sched.next_fire))

        # now update, should advance to next thursday (present time)
        now = timezone.now()
        next_update = datetime(now.year, now.month, now.day, hour=10).replace(tzinfo=timezone.pytz.utc)

        # make sure we are looking at the following week if it is a thursday
        if next_update.weekday() == THURSDAY:  # pragma: no cover
            next_update += timedelta(days=7)

        else:  # pragma: no cover
            # add days until we get to the next thursday
            while next_update.weekday() != THURSDAY:
                next_update += timedelta(days=1)

        self.assertTrue(sched.update_schedule())
        self.assertEquals(next_update, sched.next_fire)

        # try a weekly schedule
        sched = self.create_schedule('W', [THURSDAY])
        self.assertEquals(datetime(2013, 1, 10, hour=10).replace(tzinfo=pytz.utc), sched.get_next_fire(sched.next_fire))
        self.assertTrue(sched.update_schedule())
        self.assertEquals(next_update, sched.next_fire)

        # lastly, a daily schedule
        sched = self.create_schedule('D')
        self.assertEquals(datetime(2013, 1, 4, hour=10).replace(tzinfo=pytz.utc), sched.get_next_fire(sched.next_fire))

        sched = self.create_schedule('M')
        self.assertEquals(datetime(2013, 2, 3, hour=10).replace(tzinfo=pytz.utc), sched.get_next_fire(sched.next_fire))
        self.assertTrue(sched.update_schedule(datetime(2013, 4, 1).replace(tzinfo=pytz.utc)))
        self.assertEquals(str(datetime(2013, 4, 3, hour=10).replace(tzinfo=pytz.utc)), str(sched.next_fire))

        sched = self.create_schedule('M', start_date=datetime(2014, 1, 31, hour=10).replace(tzinfo=pytz.utc))
        self.assertEquals(datetime(2014, 2, 28, hour=10).replace(tzinfo=pytz.utc), sched.get_next_fire(sched.next_fire))
        self.assertTrue(sched.update_schedule(datetime(2014, 3, 31).replace(tzinfo=pytz.utc)))
        self.assertEquals(str(datetime(2014, 4, 30, hour=10).replace(tzinfo=pytz.utc)), str(sched.next_fire))

        sched = self.create_schedule('M', start_date=datetime(2014, 1, 31, hour=10).replace(tzinfo=pytz.utc))
        self.assertEquals(datetime(2014, 2, 28, hour=10).replace(tzinfo=pytz.utc), sched.get_next_fire(datetime(2014, 2, 27, hour=10).replace(tzinfo=pytz.utc)))

    def test_schedule_ui(self):

        self.login(self.admin)

        joe = self.create_contact("Joe Blow", "123")

        # test missing recipients
        post_data = dict(text="message content", omnibox="", sender=self.channel.pk, _format="json", schedule=True)
        response = self.client.post(reverse('msgs.broadcast_send'), post_data, follow=True)
        self.assertIn("At least one recipient is required", response.content)

        # missing message
        post_data = dict(text="", omnibox="c-%d" % joe.pk, sender=self.channel.pk, _format="json", schedule=True)
        response = self.client.post(reverse('msgs.broadcast_send'), post_data, follow=True)
        self.assertIn("This field is required", response.content)

        # finally create our message
        post_data = dict(text="A scheduled message to Joe", omnibox="c-%d" % joe.pk, sender=self.channel.pk, _format="json", schedule=True)
        response = json.loads(self.client.post(reverse('msgs.broadcast_send'), post_data, follow=True).content)
        self.assertIn("/broadcast/schedule_read", response['redirect'])

        # fetch our formax page
        response = self.client.get(response['redirect'])
        self.assertContains(response, "id-schedule")
        broadcast = response.context['object']

        # update our message
        post_data = dict(message="An updated scheduled message", omnibox="c-%d" % joe.pk)
        self.client.post(reverse('msgs.broadcast_update', args=[broadcast.pk]),  post_data)
        self.assertEquals("An updated scheduled message", Broadcast.objects.get(pk=broadcast.pk).text)

        # update the schedule
        post_data = dict(repeat_period='W', repeat_days=6, start='later', start_datetime_value=1)
        response = self.client.post(reverse('schedules.schedule_update', args=[broadcast.schedule.pk]),  post_data)

        #broadcast = Broadcast.objects.get(pk=broadcast.pk)
        #self.assertTrue(broadcast.schedule.has_pending_fire())

    def test_update(self):
        sched = self.create_schedule('W', [THURSDAY, SATURDAY])
        update_url = reverse('schedules.schedule_update', args=[sched.pk])

        # viewer can't access
        self.login(self.user)
        response = self.client.get(update_url)
        self.assertLoginRedirect(response)

        # editor can access
        self.login(self.editor)
        response = self.client.get(update_url)
        self.assertEqual(response.status_code, 200)

        # as can admin user
        self.login(self.admin)
        response = self.client.get(update_url)
        self.assertEqual(response.status_code, 200)

        now = timezone.now()
        now_stamp = time.mktime(now.timetuple())

        tommorrow = now + timedelta(days=1)
        tommorrow_stamp = time.mktime(tommorrow.timetuple())

        post_data = dict()
        post_data['start'] = 'never'
        post_data['repeat_period'] = 'O'

        response = self.client.post(update_url, post_data)

        schedule = Schedule.objects.get(pk=sched.pk)
        self.assertEquals(schedule.status, 'U')

        post_data = dict()
        post_data['start'] = 'stop'
        post_data['repeat_period'] = 'O'

        response = self.client.post(update_url, post_data)

        schedule = Schedule.objects.get(pk=sched.pk)
        self.assertEquals(schedule.status, 'U')

        post_data = dict()
        post_data['start'] = 'now'
        post_data['repeat_period'] = 'O'
        post_data['start_datetime_value'] = "%d" % now_stamp

        response = self.client.post(update_url, post_data)

        schedule = Schedule.objects.get(pk=sched.pk)
        self.assertEquals(schedule.repeat_period, 'O')
        self.assertFalse(schedule.next_fire)

        post_data = dict()
        post_data['repeat_period'] = 'D'
        post_data['start'] = 'later'
        post_data['start_datetime_value'] = "%d" % tommorrow_stamp

        response = self.client.post(update_url, post_data)

        schedule = Schedule.objects.get(pk=sched.pk)
        self.assertEquals(schedule.repeat_period, 'D')

        post_data = dict()
        post_data['repeat_period'] = 'D'
        post_data['start'] = 'later'

        response = self.client.post(update_url, post_data)

        schedule = Schedule.objects.get(pk=sched.pk)
        self.assertEquals(schedule.repeat_period, 'D')

    def test_calculating_next_fire(self):

        self.org.timezone = 'US/Eastern'
        self.org.save()

        tz = self.org.get_tzinfo()
        eleven_pm_est = datetime(2013, 1, 3, hour=23, minute=0, second=0, microsecond=0).replace(tzinfo=tz)

        # Test date is 10am on a Thursday, Jan 3rd
        schedule = self.create_schedule('D', start_date=eleven_pm_est)
        schedule.save()

        Broadcast.create(self.org, self.admin, 'Message', [], schedule=schedule)
        schedule = Schedule.objects.get(pk=schedule.pk)

        # when is the next fire once our first one passes
        sched_date = datetime(2013, 1, 3, hour=23, minute=30, second=0, microsecond=0).replace(tzinfo=tz)
        schedule.update_schedule(sched_date)
        self.assertEquals('2013-01-04 23:00:00-05:00', unicode(schedule.next_fire))

    def test_update_near_day_boundary(self):

        self.org.timezone = 'US/Eastern'
        self.org.save()
        tz = self.org.get_tzinfo()

        sched = self.create_schedule('D')
        Broadcast.create(self.org, self.admin, 'Message', [], schedule=sched)
        sched = Schedule.objects.get(pk=sched.pk)

        update_url = reverse('schedules.schedule_update', args=[sched.pk])

        self.login(self.admin)

        # way off into the future
        start_date = datetime(2050, 1, 3, 23, 0, 0, 0, tzinfo=tz)
        start_date = pytz.utc.normalize(start_date.astimezone(pytz.utc))

        post_data = dict()
        post_data['repeat_period'] = 'D'
        post_data['start'] = 'later'
        post_data['start_datetime_value'] = "%d" % time.mktime(start_date.timetuple())
        self.client.post(update_url, post_data)
        sched = Schedule.objects.get(pk=sched.pk)

        # 11pm in NY should be 4am UTC the next day
        self.assertEquals('2050-01-04 04:00:00+00:00', unicode(sched.next_fire))

        # a time in the past
        start_date = datetime(2010, 1, 3, 23, 0, 0, 0, tzinfo=tz)
        start_date = pytz.utc.normalize(start_date.astimezone(pytz.utc))

        post_data = dict()
        post_data['repeat_period'] = 'D'
        post_data['start'] = 'later'
        post_data['start_datetime_value'] = "%d" % time.mktime(start_date.timetuple())
        self.client.post(update_url, post_data)
        sched = Schedule.objects.get(pk=sched.pk)

        # next fire should fall at the same hour
        self.assertIn('04:00:00+00:00', unicode(sched.next_fire))


